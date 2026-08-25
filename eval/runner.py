"""Ejecuta el agente del módulo indicado contra escenarios del mundo (M3).

Reutiliza el mismo patrón que `mia_world.cli._cmd_run`: `build_agent(config)`
fresco por caso + `make_world_tools(world)` registradas sobre esa instancia.
A diferencia del CLI (pensado para una corrida manual), soporta múltiples
trials por escenario (el LLM es no determinístico) partiendo cada uno de un
`World` prístino, y overrides de configuración para reutilizarse tanto en la
corrida baseline como en los experimentos.
"""

from __future__ import annotations

import copy
import importlib
import time
from dataclasses import asdict
from typing import Any, Callable

from mia_world.goals import check_goal
from mia_world.state import Scenario, World
from mia_world.tools import make_world_tools


def _instrument_goal_progress(agent: Any, world: World, goal: dict[str, Any]) -> dict[str, Any]:
    """Envuelve *todas* las tools ya registradas en `agent` para detectar en qué
    invocación se cumplió `goal` por primera vez.

    `check_goal` normalmente solo se llama una vez, al final de `run()`, contra
    el `World` final — eso dice *si* se logró la meta pero no *en qué paso*.
    Para saberlo sin tocar `student_framework/agent.py` (que no expone hooks
    por-paso), reemplazamos cada callable en `agent._tools` por una versión
    que cuenta invocaciones y re-evalúa `check_goal` después de cada una. El
    contador se alinea 1:1 con `AgentResult.steps` porque `_execute_tool` del
    agente llama exactamente una vez a `self._tools[name](**kwargs)` por cada
    `AgentStep` que registra (éxito o error).

    Limitación conocida: si el agente reintenta una tool internamente ante un
    fallo transitorio (`max_tool_retries`), esa tool se invocaría más de una
    vez por `AgentStep` y el contador se desalinearía. No ocurre en la
    práctica con las tools del mundo (deterministas, no lanzan errores que
    `_is_transient_error` clasifique como transitorios).
    """
    progress: dict[str, Any] = {"calls": 0, "goal_achieved_at_step": None}

    def _wrap(fn: Callable[..., str]) -> Callable[..., str]:
        def wrapped(*args: Any, **kwargs: Any) -> str:
            try:
                return fn(*args, **kwargs)
            finally:
                progress["calls"] += 1
                if progress["goal_achieved_at_step"] is None:
                    achieved, _ = check_goal(world, goal)
                    if achieved:
                        progress["goal_achieved_at_step"] = progress["calls"]

        return wrapped

    #Aca es donde haceos el wrap de las tools del agente para instrumentar el progreso hacia la meta
    for name, fn in list(agent._tools.items()):  # noqa: SLF001 — instrumentación externa deliberada
        agent._tools[name] = _wrap(fn)

    return progress


def run_case(
    scenario: Scenario,
    *,
    module_name: str = "student_framework",
    config: dict[str, Any] | None = None,
    trial: int = 0,
) -> dict[str, Any]:
    """Corre el agente una vez sobre `scenario` y captura entrada/salida/estado.

    `scenario.initial_world` se copia (`copy.deepcopy`) antes de cada corrida:
    las tools del mundo mutan el `World` en sitio, así que reusar la misma
    instancia entre trials contaminaría el estado inicial de los siguientes.
    """
    module = importlib.import_module(module_name) # esto es una mugre pero no se como hacerlo mejor porque viene ya mal desde el framework del tp
    world = copy.deepcopy(scenario.initial_world)

    agent = module.build_agent(dict(config or {}))
    for fn, schema in make_world_tools(world):
        agent.register_tool(fn, schema)
    progress = _instrument_goal_progress(agent, world, scenario.goal)

    start = time.monotonic()
    run_error: str | None = None
    result = None
    try:
        result = agent.run(scenario.user_message)
    except Exception as exc:
        # El contrato de `Agent.run` dice que nunca debería lanzar, pero un
        # caso de evaluación individual no debe abortar la corrida completa
        # de la suite: se captura y se registra como fallo de ese caso.
        run_error = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - start

    if run_error is not None:
        achieved, reason = False, f"excepción no capturada durante run(): {run_error}"
    else:
        achieved, reason = check_goal(world, scenario.goal)

    return {
        "scenario": scenario.id,
        "difficulty": scenario.difficulty,
        "trial": trial,
        "goal": scenario.goal,
        "goal_achieved": achieved,
        "goal_reason": reason,
        "goal_achieved_at_step": progress["goal_achieved_at_step"],
        "wall_clock_seconds": elapsed,
        "agent_result": asdict(result) if result is not None else None,
        "run_error": run_error,
        "event_log": list(world.event_log),
    }


def run_suite(
    scenarios: list[Scenario],
    *,
    module_name: str = "student_framework",
    config: dict[str, Any] | None = None,
    trials: int = 1,
    on_case: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Corre `trials` repeticiones de cada escenario. Devuelve la lista de casos.

    `on_case` es un callback opcional invocado tras cada caso individual —
    útil para imprimir progreso en corridas largas/pagas contra un proveedor
    real, sin acoplar este módulo a ninguna forma de logging en particular.
    """
    cases: list[dict[str, Any]] = []
    for scenario in scenarios:
        for trial in range(trials):
            case = run_case(scenario, module_name=module_name, config=config, trial=trial)
            cases.append(case)
            if on_case is not None:
                on_case(case)
    return cases
