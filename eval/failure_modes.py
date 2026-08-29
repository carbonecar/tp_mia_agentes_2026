"""Categorización de modos de fallo a partir de los casos que produce `runner.py`.

Cada categoría se deriva únicamente de campos observables en `AgentResult`/
`AgentStep` (no inspecciona el `World` más allá de lo que ya expone
`check_goal`), así que son heurísticas, no certezas — se documentan sus
límites en cada función. Ningún caso exitoso (`goal_achieved`) se categoriza.
"""

from __future__ import annotations

from typing import Any

RUN_EXCEPTION = "excepcion_no_capturada"
LLM_ERROR = "fallo_llm_no_transitorio"
MAX_ITERATIONS_EXHAUSTED = "max_iterations_agotado"
HALLUCINATED_TOOL_CALL = "tool_call_alucinado"
WORLD_TOOL_ARGUMENT_ERROR = "argumento_invalido_tool_mundo"
REPEATED_FAILED_ACTION = "accion_repetida_fallida"
CONTEXT_OVERFLOW = "desborde_de_contexto"
SEQUENCE_ORDER_VIOLATED = "orden_de_secuencia_violado"
MULTI_ROOM_MAP_LOST = "perdida_de_mapa_multi_sala"
STOPPED_WITHOUT_GOAL = "se_detuvo_sin_lograr_la_meta"
UNKNOWN = "sin_categorizar"

_MULTI_ROOM_SCENARIOS = {"apartment-keys", "office-sequence", "vault-combination", "backtracking-vault"}


def _step_failed(step: dict[str, Any]) -> bool:
    """Un `AgentStep` cuenta como fallido si tiene `error` (excepción de
    Python capturada por `_execute_tool`) **o** si su `tool_output` es un
    "error suave": varias tools de `mia_world` (fijas, no las nuestras)
    señalan un fallo devolviendo un string `"Error: ..."` como valor de
    retorno normal en vez de lanzar (p. ej. `go` contra una salida
    bloqueada) — así que `AgentStep.error` queda en `None` aunque la acción
    haya fallado semánticamente. Sin este chequeo, `REPEATED_FAILED_ACTION`
    subdetecta sistemáticamente los fallos de tools del mundo.
    """
    if step.get("error"):
        return True
    output = step.get("tool_output") or ""
    return output.startswith("Error:")


def classify_failure(case: dict[str, Any]) -> list[str]:
    """Devuelve las categorías de fallo aplicables a `case`. Vacío si tuvo éxito."""
    if case.get("goal_achieved"):
        return []

    if case.get("run_error"):
        # El agente lanzó una excepción no capturada por su propio bucle
        # (viola el contrato de M1/M2 de nunca lanzar) — nada más es
        # diagnosticable de forma fiable a partir de acá.
        return [RUN_EXCEPTION]

    agent_result = case.get("agent_result") or {}
    steps: list[dict[str, Any]] = agent_result.get("steps") or []
    categories: list[str] = []

    if agent_result.get("error"):
        # Fallo transitorio del LLM que agotó `max_llm_retries` dentro de run().
        categories.append(LLM_ERROR)

    # `run()` solo devuelve `answer == ""` al agotar `max_iterations` sin una
    # respuesta final de texto (ver student_framework/agent.py). Es la señal
    # más directa de "se quedó sin presupuesto de pasos".
    if not agent_result.get("answer") and not agent_result.get("error"):
        categories.append(MAX_ITERATIONS_EXHAUSTED)

    if any("Herramienta desconocida" in (s.get("error") or "") for s in steps):
        categories.append(HALLUCINATED_TOOL_CALL)

    # Las tools de `mia_world` (fijas, no las nuestras) no validan kwargs con
    # mensajes accionables: un nombre de parámetro equivocado revienta como
    # `TypeError` crudo ("...got an unexpected keyword argument...",
    # "...missing N required positional argument..."), que nuestro
    # `_execute_tool` captura sin crashear pero tampoco puede enriquecer.
    if any(
        "unexpected keyword argument" in (s.get("error") or "") or "positional argument" in (s.get("error") or "")
        for s in steps
    ):
        categories.append(WORLD_TOOL_ARGUMENT_ERROR)

    error_action_counts: dict[tuple[str | None, str | None], int] = {}
    for s in steps:
        if _step_failed(s):
            key = (s.get("tool_name"), s.get("tool_input"))
            error_action_counts[key] = error_action_counts.get(key, 0) + 1
    if any(count >= 2 for count in error_action_counts.values()):
        categories.append(REPEATED_FAILED_ACTION)

    if case["scenario"] == "extreme-archive" and MAX_ITERATIONS_EXHAUSTED in categories:
        # El enunciado señala este escenario específicamente como diseñado
        # para no caber en el contexto de modelos chicos; agotar el
        # presupuesto de pasos ahí es la señal disponible de que el agente
        # perdió disciplina de tool-calling examinando expedientes de más.
        categories.append(CONTEXT_OVERFLOW)

    if case["scenario"] == "office-sequence" and "orden" in (case.get("goal_reason") or "").lower():
        categories.append(SEQUENCE_ORDER_VIOLATED)

    if case["scenario"] in _MULTI_ROOM_SCENARIOS:
        go_targets = [s.get("tool_input") for s in steps if s.get("tool_name") == "go"]
        # Heurística aproximada: navegar más del doble de veces que
        # direcciones distintas pidió sugiere ida-y-vuelta sin necesidad,
        # no navegación dirigida. No distingue backtracking legítimo
        # (p. ej. `backtracking-vault`, que lo requiere por diseño) de
        # extravío real — usar junto con la transcripción, no aislado.
        if len(go_targets) >= 4 and len(go_targets) > 2 * len(set(go_targets)):
            categories.append(MULTI_ROOM_MAP_LOST)

    if not categories:
        if agent_result.get("answer"):
            # El agente terminó con una respuesta de texto (no agotó pasos, no
            # hubo error) pero el mundo no llegó a la meta: se detuvo por su
            # cuenta creyendo haber terminado (o rindiéndose) sin lograrlo.
            categories.append(STOPPED_WITHOUT_GOAL)
        else:
            categories.append(UNKNOWN)
    return categories


def summarize(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Tabla categoría x escenario -> conteo, para pegar en `INFORME.md`."""
    table: dict[str, dict[str, int]] = {}
    for case in cases:
        for category in classify_failure(case):
            row = table.setdefault(category, {})
            row[case["scenario"]] = row.get(case["scenario"], 0) + 1
    return table


def summary_to_markdown_table(summary: dict[str, dict[str, int]]) -> str:
    scenarios = sorted({sc for row in summary.values() for sc in row})
    if not summary:
        return "(sin fallos categorizados — todos los casos lograron la meta)"
    header = "| Categoría | " + " | ".join(scenarios) + " | Total |"
    sep = "|---|" + "---:|" * (len(scenarios) + 1)
    lines = [header, sep]
    for category, row in sorted(summary.items()):
        counts = [str(row.get(sc, "")) or "—" for sc in scenarios]
        total = sum(row.values())
        lines.append(f"| {category} | " + " | ".join(counts) + f" | {total} |")
    return "\n".join(lines)
