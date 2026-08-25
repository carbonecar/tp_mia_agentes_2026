"""Métricas cuantitativas y cualitativas sobre los casos producidos por `runner.py`."""

from __future__ import annotations

from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

# Cantidad óptima de tool-calls por escenario (tabla de ENUNCIADO_M3.md). No
# vive en el JSON del escenario, así que se hardcodea acá.
OPTIMAL_CALLS: dict[str, int] = {
    "study-with-key": 3,
    "color-locks": 11,
    "apartment-keys": 7,
    "library-search": 7,
    "office-sequence": 13,
    "extreme-archive": 4,
    "vault-combination": 21,
    "backtracking-vault": 18,
}


def case_quantitative_metrics(case: dict[str, Any]) -> dict[str, Any]:
    """Métricas de un caso individual (una corrida de un escenario)."""
    agent_result = case.get("agent_result") or {}
    steps = agent_result.get("steps") or []
    tool_calls_used = len(steps)
    optimal = OPTIMAL_CALLS.get(case["scenario"])
    # >1.0 imposible (no hay forma de usar menos calls que el óptimo); <1.0
    # indica que el agente "vagabundeó" más de lo necesario. Se basa en el
    # total de pasos del run, así que penaliza también acciones hechas
    # *después* de haber cumplido la meta (ver `goal_achieved_at_step`).
    efficiency_ratio = (optimal / tool_calls_used) if optimal and tool_calls_used else None

    goal_achieved_at_step = case.get("goal_achieved_at_step")
    # Eficiencia "real": pasos hasta cumplir la meta, sin contar lo que el
    # agente haya hecho después (p. ej. un `look` final de confirmación).
    # Solo tiene sentido cuando la meta se cumplió.
    real_efficiency_ratio = (
        (optimal / goal_achieved_at_step) if optimal and goal_achieved_at_step else None
    )

    return {
        "scenario": case["scenario"],
        "difficulty": case["difficulty"],
        "trial": case["trial"],
        "goal_achieved": bool(case["goal_achieved"]),
        "goal_achieved_at_step": goal_achieved_at_step,
        "tool_calls_used": tool_calls_used,
        "optimal_calls": optimal,
        "efficiency_ratio": efficiency_ratio,
        "real_efficiency_ratio": real_efficiency_ratio,
        "input_tokens": agent_result.get("input_tokens"),
        "output_tokens": agent_result.get("output_tokens"),
        "wall_clock_seconds": case.get("wall_clock_seconds"),
        "run_error": case.get("run_error"),
    }


def _mean_or_none(values: list[float | int | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega métricas por escenario y globalmente a partir de una lista de casos crudos."""
    per_case = [case_quantitative_metrics(c) for c in cases]

    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for m in per_case:
        by_scenario.setdefault(m["scenario"], []).append(m)

    scenario_summaries: dict[str, dict[str, Any]] = {}
    for scenario_id, metrics_list in by_scenario.items():
        n = len(metrics_list)
        successes = sum(1 for m in metrics_list if m["goal_achieved"])
        scenario_summaries[scenario_id] = {
            "difficulty": metrics_list[0]["difficulty"],
            "trials": n,
            "success_rate": successes / n if n else None,
            "mean_tool_calls_used": _mean_or_none([m["tool_calls_used"] for m in metrics_list]),
            "optimal_calls": metrics_list[0]["optimal_calls"],
            "mean_efficiency_ratio": _mean_or_none([m["efficiency_ratio"] for m in metrics_list]),
            # Solo sobre los trials exitosos: en cuántos pasos se cumplió la
            # meta, sin contar lo que el agente haya hecho después.
            "mean_steps_to_goal": _mean_or_none([m["goal_achieved_at_step"] for m in metrics_list]),
            "mean_real_efficiency_ratio": _mean_or_none([m["real_efficiency_ratio"] for m in metrics_list]),
            "mean_input_tokens": _mean_or_none([m["input_tokens"] for m in metrics_list]),
            "mean_output_tokens": _mean_or_none([m["output_tokens"] for m in metrics_list]),
            "mean_wall_clock_seconds": _mean_or_none([m["wall_clock_seconds"] for m in metrics_list]),
        }

    n_total = len(per_case)
    overall = {
        "trials_total": n_total,
        "success_rate": (sum(1 for m in per_case if m["goal_achieved"]) / n_total) if n_total else None,
        "mean_efficiency_ratio": _mean_or_none([m["efficiency_ratio"] for m in per_case]),
        "mean_input_tokens": _mean_or_none([m["input_tokens"] for m in per_case]),
        "mean_output_tokens": _mean_or_none([m["output_tokens"] for m in per_case]),
        "mean_wall_clock_seconds": _mean_or_none([m["wall_clock_seconds"] for m in per_case]),
    }

    return {"overall": overall, "by_scenario": scenario_summaries}


def to_markdown_table(summary: dict[str, Any]) -> str:
    """Tabla Markdown lista para pegar en `INFORME.md`."""
    lines = [
        "| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario_id, s in summary["by_scenario"].items():
        success_pct = f"{s['success_rate'] * 100:.0f}%" if s["success_rate"] is not None else "—"
        calls = f"{s['mean_tool_calls_used']:.1f} / {s['optimal_calls']}" if s["mean_tool_calls_used"] is not None else "—"
        eff = f"{s['mean_efficiency_ratio']:.2f}" if s["mean_efficiency_ratio"] is not None else "—"
        step_to_goal = f"{s['mean_steps_to_goal']:.1f}" if s["mean_steps_to_goal"] is not None else "—"
        tok_in = f"{s['mean_input_tokens']:.0f}" if s["mean_input_tokens"] is not None else "—"
        tok_out = f"{s['mean_output_tokens']:.0f}" if s["mean_output_tokens"] is not None else "—"
        lat = f"{s['mean_wall_clock_seconds']:.1f}" if s["mean_wall_clock_seconds"] is not None else "—"
        lines.append(
            f"| {scenario_id} | {s['difficulty']} | {s['trials']} | {success_pct} | {calls} | "
            f"{eff} | {step_to_goal} | {tok_in}/{tok_out} | {lat} |"
        )
    overall = summary["overall"]
    overall_success = f"{overall['success_rate'] * 100:.0f}%" if overall["success_rate"] is not None else "—"
    lines.append(
        f"| **TOTAL** | — | {overall['trials_total']} | **{overall_success}** | — | — | — | — | — |"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dimensión cualitativa: rúbrica vía LLM-as-judge
# ---------------------------------------------------------------------------


class QualitativeReview(BaseModel):
    """Rúbrica de 3 dimensiones (1-5) sobre la transcripción de un caso.

    Complementa `goal_achieved` (binario): un agente puede fallar por poco
    (casi resuelve `office-sequence` pero invierte el orden) o divagar sin
    rumbo — el booleano no distingue esos dos casos, la rúbrica sí.
    """

    exploracion_dirigida: int = Field(ge=1, le=5, description="1=acciones erráticas/redundantes, 5=cada acción reduce incertidumbre sobre el objetivo.")
    exploracion_dirigida_justificacion: str
    recuperacion_de_errores: int = Field(ge=1, le=5, description="1=repite el mismo error sin corregir, 5=corrige inmediatamente a partir del mensaje de error.")
    recuperacion_de_errores_justificacion: str
    uso_de_planificacion: int = Field(ge=1, le=5, description="1=puramente reactivo paso a paso, 5=evidencia de descomponer el objetivo en sub-metas.")
    uso_de_planificacion_justificacion: str


def _format_transcript(case: dict[str, Any]) -> str:
    agent_result = case.get("agent_result") or {}
    steps = agent_result.get("steps") or []
    lines = []
    for i, step in enumerate(steps, start=1):
        status = f"ERROR: {step['error']}" if step.get("error") else f"resultado: {step.get('tool_output')!r}"
        lines.append(f"{i}. {step.get('tool_name')}({step.get('tool_input')}) -> {status}")
    lines.append(f"Respuesta final del agente: {agent_result.get('answer')!r}")
    return "\n".join(lines) if lines else "(sin pasos registrados)"


def judge_case(judge_agent: Any, case: dict[str, Any], scenario_description: str) -> QualitativeReview | None:
    """Pide al `judge_agent` (una instancia de `Agent`, típicamente sin tools)
    que puntúe la transcripción de `case` vía `structured_call`.

    Devuelve `None` si el juez no logra producir una rúbrica válida (se
    agotaron los reintentos de reparación) — un fallo del juez no debe
    abortar la evaluación del resto de los casos.
    """
    transcript = _format_transcript(case)
    prompt = (
        "Sos un evaluador experto de agentes LLM que resuelven puzzles tipo "
        "escape-room manipulando un mundo simulado con herramientas (look/"
        "examine/take/use/go).\n\n"
        f"Escenario: {scenario_description}\n"
        f"Meta lograda: {case['goal_achieved']} ({case['goal_reason']})\n\n"
        f"Transcripción de acciones del agente:\n{transcript}\n\n"
        "Calificá al agente en cada dimensión de 1 (muy pobre) a 5 (excelente), "
        "con una justificación breve (1-2 oraciones) por dimensión."
    )
    try:
        return judge_agent.structured_call(prompt=prompt, schema=QualitativeReview)
    except Exception:
        return None
