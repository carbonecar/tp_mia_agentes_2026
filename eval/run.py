"""CLI de evaluación de M3: corre el agente contra el dataset de escenarios.

Uso típico:

    # Smoke test barato (Ollama local, 1 escenario, 1 trial)
    python eval/run.py --scenarios study-with-key --trials 1 --label smoke

    # Corrida baseline completa
    python eval/run.py --scenarios all --trials 3 --label baseline

    # Experimento: ventana de historial chica
    python eval/run.py --scenarios all --trials 3 --label exp-history-8 \\
        --max-history-messages 8

Reproducible sin pasos manuales: una sola invocación deja JSON crudo por
caso + un resumen (`summary.json` y `summary.md`) en `eval/results/<label>/`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mia_world.scenarios import list_scenarios  # noqa: E402
from mia_world.state import Scenario  # noqa: E402

from eval import failure_modes, metrics  # noqa: E402
from eval.runner import AGENT_MODES, run_suite  # noqa: E402

DEFAULT_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "results"



def _select_scenarios(specs: list[str], scenarios_dir: Path) -> list[Scenario]:
    """Resuelve `specs` (ids, dificultades, o `["all"]`) a la lista de escenarios.

    A diferencia de `mia_world.cli._resolve_scenario` (pensada para un único
    escenario manual), una dificultad acá expande a *todos* sus escenarios
    (p. ej. "medium" -> color-locks + apartment-keys), que es lo que necesita
    una corrida de evaluación.
    """
    available = list_scenarios(scenarios_dir)
    if len(specs) == 1 and specs[0] == "all":
        return available

    by_id = {sc.id: sc for sc in available}
    selected: dict[str, Scenario] = {}
    for spec in specs:
        if spec in by_id:
            selected[spec] = by_id[spec]
            continue
        by_difficulty = [sc for sc in available if sc.difficulty == spec]
        if by_difficulty:
            for sc in by_difficulty:
                selected[sc.id] = sc
            continue
        options = ", ".join(sorted(sc.id for sc in available))
        raise SystemExit(f"No se encontró el escenario o dificultad {spec!r}. Disponibles: {options}.")
    return list(selected.values())


@dataclasses.dataclass
class EvalArgs:
    """Argumentos de línea de comandos de `eval.run`."""

    scenarios: list[str]
    scenarios_dir: str
    trials: int
    module: str
    out: str
    label: str
    config: str | None
    max_history_messages: int | None
    max_iterations: int | None
    system_prompt: str | None
    system_prompt_file: str | None
    planner: bool
    adaptive: bool
    agent_mode: str
    room_graph: bool
    case_timeout_seconds: float | None
    judge: bool

    @classmethod
    def parse(cls, argv: list[str] | None = None) -> "EvalArgs":
        parser = argparse.ArgumentParser(prog="eval.run", description=__doc__)
        parser.add_argument("--scenarios", nargs="+", default=["all"], help="ids, dificultades, o 'all' (default).")
        parser.add_argument("--scenarios-dir", default=str(DEFAULT_SCENARIOS_DIR))
        parser.add_argument("--trials", type=int, default=1, help="repeticiones por escenario (el LLM es no determinístico).")
        parser.add_argument("--module", default="student_framework", help="módulo que expone build_agent.")
        parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="directorio raíz de resultados.")
        parser.add_argument("--label", default="run", help="nombre de esta corrida/experimento; determina el subdirectorio de salida.")
        parser.add_argument("--config", default=None, help="path a un JSON con overrides arbitrarios de build_agent config.")
        parser.add_argument("--max-history-messages", type=int, default=None)
        parser.add_argument("--max-iterations", type=int, default=None)
        prompt_group = parser.add_mutually_exclusive_group()
        prompt_group.add_argument("--system-prompt", default=None, help="system prompt inline.")
        prompt_group.add_argument(
            "--system-prompt-file",
            default=None,
            help="path a un .txt con el system prompt (p. ej. prompts/baseline_prompt.txt).",
        )
        parser.add_argument(
            "--planner",
            action="store_true",
            help=(
                "activa la fase de planificación explícita (`MyAgent(planner=True)`): "
                "antes de la primera respuesta, el agente descompone el objetivo en "
                "sub-metas ordenadas vía `structured_call` (experimento 'planner "
                "explícito vs. ReAct puro')."
            ),
        )
        parser.add_argument(
            "--agent-mode",
            choices=AGENT_MODES,
            default="flat",
            help=(
                "'flat' (default): un único agente decide look/examine/take/use/go. "
                "'subagent': el agente solo decide take/use/go y delega look/examine "
                "en un sub-agente 'explorador' aparte, vía la tool `explorar_sala` "
                "(experimento de delegación de tools). "
                "'adaptive': registra ambas rutas a la vez (look/examine directas Y "
                "explorar_sala) — combinar con --adaptive para que el propio modelo "
                "decida, por escenario, cuál usar."
            ),
        )
        parser.add_argument(
            "--adaptive",
            action="store_true",
            help=(
                "activa la capa adaptativa (`MyAgent(adaptive=True)`): en vez de "
                "planificar siempre (--planner) o nunca, la primera llamada dispara "
                "una fase de triage donde el propio modelo evalúa la complejidad "
                "aparente del objetivo y decide si conviene un plan de sub-metas y/o "
                "delegar la exploración a `explorar_sala` (si está registrada — "
                "combinar con --agent-mode adaptive para que lo esté). Tiene "
                "precedencia sobre --planner si se pasan los dos."
            ),
        )
        parser.add_argument(
            "--room-graph",
            action="store_true",
            help=(
                "agrega la tool `consultar_mapa` (sin LLM, sin costo): un mapa "
                "determinístico de las salas ya visitadas y sus salidas, armado "
                "directo desde el `World` (ver "
                "`student_framework.tools.room_graph`). Independiente de "
                "`--agent-mode`: se puede combinar con `flat`, `subagent` o "
                "`adaptive` para comparar con/sin mapa en cualquiera de los tres."
            ),
        )
        parser.add_argument(
            "--case-timeout-seconds",
            type=float,
            default=None,
            help=(
                "corta un caso individual si `agent.run()` no termina dentro de este "
                "límite (harness de evaluación, ver `eval/runner.py::_case_time_limit`) "
                "— el caso queda marcado como fallo (`caso_timeout_abortado`) pero la "
                "suite sigue con el resto. Default: sin límite, como antes de este flag. "
                "Solo tiene efecto en sistemas POSIX (usa SIGALRM)."
            ),
        )
        parser.add_argument("--judge", action="store_true", help="corre además el juez cualitativo (LLM-as-judge) por caso — costo extra.")
        ns = parser.parse_args(argv)
        return cls(**vars(ns))


def _build_config(args: EvalArgs) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if args.config:
        config.update(json.loads(Path(args.config).read_text(encoding="utf-8")))
    if args.max_history_messages is not None:
        config["max_history_messages"] = args.max_history_messages
    if args.max_iterations is not None:
        config["max_iterations"] = args.max_iterations
    if args.system_prompt is not None:
        config["system_prompt"] = args.system_prompt
    if args.system_prompt_file is not None:
        path = Path(args.system_prompt_file)
        if not path.is_file():
            raise SystemExit(f"No existe el archivo de system prompt: {path}")
        config["system_prompt"] = path.read_text(encoding="utf-8").strip()
    if args.planner:
        config["planner"] = True
    if args.adaptive:
        config["adaptive"] = True
    return config

def _build_judge_agent(args: EvalArgs) -> Any:
    if not args.judge:
        return None
    module = __import__(args.module, fromlist=["build_agent"])
    return module.build_agent()

def main(argv: list[str] | None = None) -> int:
    args = EvalArgs.parse(argv)

    scenarios = _select_scenarios(args.scenarios, Path(args.scenarios_dir))
    config = _build_config(args)

    out_dir = Path(args.out) / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"# Corriendo {len(scenarios)} escenario(s) x {args.trials} trial(s) = {len(scenarios) * args.trials} casos", file=sys.stderr)
    print(f"# módulo={args.module} config={config or '(default)'}", file=sys.stderr)

    judge_agent = _build_judge_agent(args)

    t0 = time.monotonic()
    completed = 0

    def on_case(case: dict[str, Any]) -> None:
        nonlocal completed
        completed += 1
        status = "OK" if case["goal_achieved"] else "FAIL"
        step_note = f", meta en paso {case['goal_achieved_at_step']}" if case["goal_achieved"] else ""
        print(
            f"  [{completed}/{len(scenarios) * args.trials}] {case['scenario']} "
            f"trial={case['trial']} -> {status} ({case['goal_reason']}{step_note})",
            file=sys.stderr,
        )
        if judge_agent is not None:
            scenario_desc = next(sc.description for sc in scenarios if sc.id == case["scenario"])
            review = metrics.judge_case(judge_agent, case, scenario_desc)
            case["qualitative_review"] = review.model_dump() if review is not None else None
        case_path = out_dir / f"case_{case['scenario']}_t{case['trial']}.json"
        case_path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")

    cases = run_suite(
        scenarios,
        module_name=args.module,
        config=config,
        trials=args.trials,
        agent_mode=args.agent_mode,
        include_room_graph=args.room_graph,
        case_timeout_seconds=args.case_timeout_seconds,
        on_case=on_case,
    )

    elapsed = time.monotonic() - t0
    summary = metrics.aggregate(cases)
    failure_summary = failure_modes.summarize(cases)
    explorer_cost_summary = metrics.aggregate_explorer_cost(cases)

    summary_json = {
        "label": args.label,
        "module": args.module,
        "config": config,
        "agent_mode": args.agent_mode,
        "room_graph": args.room_graph,
        "case_timeout_seconds": args.case_timeout_seconds,
        "trials_per_scenario": args.trials,
        "wall_clock_seconds_total": elapsed,
        "metrics": summary,
        "failure_modes": failure_summary,
        "explorer_cost": explorer_cost_summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary_json, indent=2, ensure_ascii=False), encoding="utf-8")

    explorer_cost_line = (
        f"\ncosto oculto del sub-agente explorador (no incluido en `input_tokens`/`output_tokens` de arriba): "
        f"{explorer_cost_summary['total_calls']} llamadas, "
        f"{explorer_cost_summary['total_input_tokens']} tokens de entrada, "
        f"{explorer_cost_summary['total_output_tokens']} tokens de salida.\n"
        if explorer_cost_summary is not None
        else ""
    )

    timeout_note = f" · case_timeout_seconds: `{args.case_timeout_seconds}`" if args.case_timeout_seconds is not None else ""
    room_graph_note = " · room_graph: `True`" if args.room_graph else ""
    markdown = (
        f"## Resultados — `{args.label}`\n\n"
        f"config: `{config or '(default)'}` · agent_mode: `{args.agent_mode}` · módulo: `{args.module}`"
        f"{room_graph_note}{timeout_note} · "
        f"{len(scenarios)} escenarios x {args.trials} trials · {elapsed:.1f}s total\n\n"
        f"{metrics.to_markdown_table(summary)}\n"
        f"{explorer_cost_line}\n"
        f"### Modos de fallo\n\n{failure_modes.summary_to_markdown_table(failure_summary)}\n"
    )
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")

    print(file=sys.stderr)
    print(markdown, file=sys.stderr)
    print(f"# Resultados en {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
