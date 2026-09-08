"""Implementación de su agente.

M1: bucle de tools básico (ver `ENUNCIADO_M1.md`).
M2: el agente pasa a ser estatal, respeta `max_history_messages` con una
ventana deslizante que nunca descarta el último mensaje de usuario, ofrece
`structured_call` con la tool sintética `final_result` (reparación ante
fallos de validación), reintenta fallos transitorios del LLM y de las
tools, y acumula tokens en `AgentResult`.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from mia_agents.protocols import LLMClient
from mia_agents.tool_schema import FINAL_RESULT_TOOL_NAME, final_result_tool_schema
from mia_agents.types import AgentResult, AgentStep, ToolSchema


class StructuredOutputError(RuntimeError):
    """Se agotaron los reintentos de reparación en `structured_call`."""


# Marca fija del mensaje sintético que `run()` deja en `AgentStep.error`
# cuando `_is_looping` bloquea un intento (ver ambos). Sirve para que
# `_is_looping` pueda filtrar sus propios bloqueos previos al mirar el
# historial — un paso bloqueado no ejecutó nada de verdad, así que no debe
# contar como "el mismo resultado de siempre" ni tampoco como "algo
# distinto que rompe el ciclo": simplemente se ignora, como si no hubiera
# pasado, y se sigue mirando la última ejecución real.
_LOOP_BLOCKED_MARKER = "ya forma parte de un patrón que se repitió sin variar"

# Cuántos fallos pendientes distintos como máximo se listan en el
# recordatorio de `remind_pending_failures` — evita que el propio
# recordatorio se vuelva ruido si el agente acumula muchos errores
# distintos a lo largo de una conversación larga. Se muestran los más
# recientes (orden de inserción del dict).
_MAX_PENDING_FAILURE_REMINDERS = 5


class _Plan(BaseModel):
    """Salida estructurada de la fase de planificación (`planner=True`).

    Reutiliza `structured_call` (ya construido para M2) en vez de un
    mecanismo nuevo: la única pieza de framework agregada es *cuándo* se
    dispara esta llamada y qué se hace con el resultado (sección "Modo
    planner" de `run`).
    """

    subgoals: list[str] = Field(
        min_length=1,
        description=(
            "Lista ordenada de 3 a 8 sub-metas concretas y verificables (no "
            "acciones sueltas de una tool, sino hitos intermedios) que hay "
            "que cumplir en ese orden para lograr el objetivo."
        ),
    )


class _Triage(BaseModel):
    """Salida estructurada de la capa adaptativa (`adaptive=True`).

    A diferencia de `planner`/`agent_mode="subagent"` (decisiones fijas,
    tomadas desde afuera antes de correr el agente), acá el propio modelo
    evalúa la complejidad aparente del objetivo — a partir únicamente del
    mensaje inicial, que en este dataset ya describe la sala y el objetivo
    de partida — y decide, caso por caso, si conviene planificar y/o
    delegar la exploración. Ver `_triage` y la sección de la capa adaptativa
    en `INFORME_M3.md`.
    """

    plan_needed: bool = Field(
        description=(
            "True si el objetivo tiene una dependencia de orden/secuencia no "
            "trivial (varias sub-metas encadenadas, navegación multi-sala, "
            "condiciones que deben cumplirse en un orden específico) que se "
            "beneficiaría de un plan explícito antes de actuar. False si el "
            "objetivo es simple y directo (una sola sala, pocos pasos "
            "evidentes) y planificar de antemano no aportaría nada."
        ),
    )
    subgoals: list[str] = Field(
        default_factory=list,
        description=(
            "Si `plan_needed` es True: lista ordenada de 3 a 8 sub-metas "
            "concretas y verificables, en el orden en que conviene "
            "perseguirlas. Si `plan_needed` es False: lista vacía."
        ),
    )
    delegate_exploration_needed: bool = Field(
        description=(
            "True si el objetivo parece involucrar suficientes salas u "
            "objetos como para que valga la pena delegar la exploración "
            "detallada de cada sala a una herramienta separada "
            "(`explorar_sala`, si está disponible) en vez de examinar todo "
            "directamente. False si el objetivo es acotado (una sola sala, "
            "pocos objetos) y delegar solo agregaría costo extra."
        ),
    )


class _Reflection(BaseModel):
    """Salida estructurada del chequeo de estancamiento (`reflect_on_stall=True`).

    A diferencia de `_Plan`/`_Triage` (se disparan una única vez, antes del
    bucle), esto se dispara *dentro* del bucle, cada vez que `_stall_streak`
    alcanza `stall_window` (ver `_reflect` y la sección "Bucle principal" de
    `run`). El propio LLM diagnostica por qué no hay progreso mirando solo
    los resultados recientes — sin que el framework tenga que reconocer
    ningún texto de error específico de `mia_world`.
    """

    diagnosis: str = Field(
        description=(
            "Una oración: por qué no se está progresando a partir de las "
            "acciones y resultados recientes (qué se repite, o qué se "
            "consiguió pero no se usó)."
        ),
    )
    next_action_hint: str = Field(
        description=(
            "Una sugerencia concreta y accionable de próximo paso, distinta "
            "de lo que se viene repitiendo."
        ),
    )


# Nombres de tools de este mundo específico (`mia_world`/
# `explorer_subagent.py`) que la capa adaptativa puede podar tras el triage
# (`_triage`, sección "Modo adaptativo" de `run`): la ruta "directa" de
# exploración y la ruta "delegada". No es un acoplamiento nuevo — `_Triage`
# ya nombra `explorar_sala` explícitamente en su descripción; esto solo
# hace explícito también el otro lado de la disyuntiva.
_DIRECT_EXPLORATION_TOOLS = ("look", "examine")
_DELEGATED_EXPLORATION_TOOL = "explorar_sala"


# ---------------------------------------------------------------------------
# Resiliencia: clasificación de errores transitorios (LLM y tools)
# ---------------------------------------------------------------------------

_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "rate limit",
    "ratelimit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "throttl",
    "temporarily unavailable",
    "service unavailable",
    "connection reset",
    "connection refused",
    "connection aborted",
    "network",
)


def _is_transient_error(exc: BaseException) -> bool:
    """Heurística de fallo transitorio: timeouts, 5xx, rate limits, red.

    No hay una jerarquía de excepciones fija compartida entre proveedores
    (Bedrock, Ollama, mocks de test), así que clasificamos por tipo conocido
    y por texto del error. Cualquier otra excepción (p. ej. errores de
    validación de argumentos) se considera permanente y aflora tal cual.
    """
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _accumulate(total: int | None, value: int | None) -> int | None:
    """
    
    Requisito de M2 contar el costo de tokens de las llamas.
    Suma `value` a `total` tratando `None` puntual como 0, sin perder el total ya iniciado.
    """
    if value is None:
        return total
    return (total or 0) + value


class MyAgent:
    """Agente autónomo de ejemplo."""

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: str = "Eres un asistente útil.",
        max_iterations: int = 10,
        max_history_messages: int = 50,
        max_llm_retries: int = 3,
        max_tool_retries: int = 2,
        retry_backoff_seconds: float = 0.05,
        planner: bool = False,
        adaptive: bool = False,
        remind_pending_failures: bool = False,
        reflect_on_stall: bool = False,
        stall_window: int = 6,
        max_consecutive_repeats: int = 2,
        max_cycle_period: int = 8,
        max_blocked_repeats: int = 5,
    ) -> None:
        """Inicializa el agente.

        Parameters
        ----------
        llm_client : LLMClient
            Cliente LLM (real o mock) que el agente utilizará.
        system_prompt : str
            System prompt por defecto.
        max_iterations : int
            Tope de iteraciones del bucle del agente por llamada a `run`.
        max_history_messages : int
            Número máximo de mensajes que se permiten en la lista
            `messages` enviada al LLM en una única llamada a `chat`. Se
            aplica con una ventana deslizante (ver `_windowed_messages`)
            que nunca descarta el último mensaje de usuario.
        max_llm_retries : int
            Reintentos ante fallos transitorios del cliente LLM.
        max_tool_retries : int
            Reintentos ante fallos transitorios de una herramienta.
        retry_backoff_seconds : float
            Backoff lineal entre reintentos (segundos).
        planner : bool
            Si es `True`, la primera llamada a `run` antepone una fase de
            planificación explícita (ver `_plan_subgoals`) antes de entrar
            al bucle ReAct habitual: el mensaje de usuario efectivo queda
            aumentado con una lista de sub-metas ordenadas. Experimento M3
            "planner explícito vs. ReAct puro" (ver `INFORME_M3.md`).
        adaptive : bool
            Si es `True`, la primera llamada a `run` dispara una fase de
            *triage* (ver `_triage`) en vez de planificar siempre o nunca:
            el propio modelo evalúa la complejidad aparente del objetivo y
            decide, caso por caso, si conviene anteponer un plan de
            sub-metas y/o delegar la exploración a `explorar_sala`. Si
            ambas rutas de exploración están registradas (`look`/`examine`
            directas y `explorar_sala` delegada), el triage **poda** la que
            no eligió en vez de solo recomendarla como texto — encontrado
            en la práctica que dejar las dos siempre disponibles le daba al
            modelo una salida constante para "explorar una vez más" en vez
            de actuar (`INFORME_M3.md`, sección 4.6). Reemplaza la decisión
            externa y fija de `planner`/`agent_mode="subagent"` por una que
            el propio agente hace por escenario. Tiene precedencia sobre
            `planner` si ambos son `True` (capa adaptativa, no una
            combinación de las dos). Ver la sección de la capa adaptativa
            en `INFORME_M3.md`.
        remind_pending_failures : bool
            Si es `True`, cada vez que una tool falla (`AgentStep.error`
            seteado, o un "error suave" — `tool_output` que empieza con
            `"Error: "`, como devuelven varias tools de `mia_world`) el
            error queda registrado por `(tool_name, arguments_json)`. En
            cada turno siguiente, mientras ese fallo siga sin resolverse,
            se le agrega al modelo un recordatorio transitorio (no se
            persiste en `self._history`, solo se agrega a los `messages`
            de esa llamada puntual) listando los fallos pendientes más
            recientes (tope: 5). Se limpia solo en cuanto esa misma
            `(tool_name, arguments_json)` se ejecuta con éxito.
            Motivación: encontrado en la práctica (`INFORME_M3.md`) que un
            agente puede reintentar la misma acción ya fallida varias veces
            a lo largo de una conversación larga sin que estén *seguidas*
            — la detección de ciclos (`_is_looping`) solo corta repeticiones
            consecutivas, así que un fallo que vuelve cada tantos pasos
            (en vez de en ráfaga) nunca llega a bloquearse, aunque
            `eval/failure_modes.py` igual lo marque como
            `accion_repetida_fallida`. Esto ataca esa causa distinta:
            mantener el error visible en cada turno en vez de dejar que se
            pierda en el historial hasta la próxima vez que se repite el
            mismo error.
        reflect_on_stall : bool
            Si es `True`, el framework lleva la cuenta de pasos consecutivos
            sin novedad — un paso "sin novedad" es uno cuyo
            `(tool_name, tool_input, tool_output, error)` ya se vio antes en
            esta corrida, sin importar si en el medio se ejecutaron otras
            tools distintas. Al llegar a `stall_window` pasos sin novedad
            seguidos, se dispara `_reflect`: una llamada aparte (vía
            `structured_call`, aislada de `self._history`) donde el propio
            modelo mira el resumen de resultados recientes y devuelve un
            diagnóstico y una sugerencia concreta de próximo paso. Esa
            sugerencia se agrega como recordatorio transitorio (no persiste
            en `self._history`) al turno inmediatamente siguiente, una sola
            vez, y el contador se reinicia.
            Motivación (`INFORME_M3.md`, sección 4.13): `remind_pending_
            failures` solo ayuda cuando el problema es "se olvidó de un
            error puntual" — pero se encontraron casos donde el agente
            **no dedujo la corrección** a partir de un error que tenía
            justo delante (reintenta con ids inventados en vez de volver a
            tomar el ítem correcto), y otros donde **no falló nada**:
            consiguió lo que necesitaba y se distrajo antes de usarlo. Ninguno
            de los dos se soluciona con más memoria de errores pasados —
            acá en cambio se le pide al propio modelo que razone sobre el
            estancamiento, en vez de intentar reconocer el patrón desde
            afuera con reglas fijas. Es una hipótesis a probar, no algo ya
            confirmado: es el mismo modelo que viene fallando en razonar el
            que tiene que auto-diagnosticarse, así que no hay garantía de
            que ayude más que `remind_pending_failures`.
        stall_window : int
            Cuántos pasos seguidos sin novedad (ver `reflect_on_stall`)
            disparan una reflexión. Sin efecto si `reflect_on_stall=False`.
        max_consecutive_repeats : int
            Cuántas veces seguidas se permite repetir el mismo *ciclo* de
            tools (de cualquier período entre 1 y `max_cycle_period`) antes
            de bloquear que se repita una vez más (ver `_is_looping`).
            Detección de ciclos: encontrado en la práctica que un agente
            puede quedar 90+ pasos repitiendo exactamente la misma acción
            sin variarla (`REENTREGA.md`, sección 5); con período 1
            (`max_cycle_period=1`) eso es justo lo que se corta, pero un
            agente también puede repetir un *bloque* de varias acciones
            distintas en el mismo orden (p. ej. re-examinar la misma lista
            de objetos una y otra vez, sección 5.2) — en vez de esperar a
            que el modelo se dé cuenta solo (el prompt ya se lo pide
            explícitamente y no alcanza), el framework corta la repetición
            él mismo, para cualquier período detectado.
        max_cycle_period : int
            Período más largo de ciclo que `_is_looping` revisa (1 = solo
            una acción idéntica consecutiva; hasta este valor cubre
            bloques de varias acciones distintas repetidas en el mismo
            orden). Mismo criterio que
            `eval/failure_modes._has_unproductive_room_cycle` usa para
            navegación entre salas, generalizado acá a cualquier tool.
        max_blocked_repeats : int
            Cuántas veces seguidas se tolera que `_is_looping` bloquee un
            intento (sin que se ejecute ninguna tool real de por medio)
            antes de cortar `run` directamente. Encontrado en la práctica
            (`REENTREGA.md`, sección 5.4): bloquear un intento no obliga al
            modelo a cambiar de estrategia — un caso real insistió con la
            misma acción ya bloqueada 86 veces seguidas hasta agotar
            `max_iterations`, sin ejecutar una sola tool real en el medio.
            El contador se reinicia en cuanto una tool se ejecuta de verdad
            (sin bloqueo); solo cuenta bloqueos *consecutivos* sin ninguna
            ejecución real entre medio.
        """
        self._llm = llm_client
        self._system = system_prompt
        self._max_iterations = max_iterations
        self._max_history_messages = max_history_messages
        self._max_llm_retries = max_llm_retries
        self._max_tool_retries = max_tool_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._planner = planner
        self._adaptive = adaptive
        self._planned = False
        self._remind_pending_failures = remind_pending_failures
        self._pending_failures: dict[str, str] = {}
        self._reflect_on_stall = reflect_on_stall
        self._stall_window = stall_window
        self._seen_step_signatures: set[tuple[str, str, str | None, str | None]] = set()
        self._stall_streak = 0
        self._active_reflection_hint: str | None = None
        self._max_consecutive_repeats = max_consecutive_repeats
        self._max_cycle_period = max_cycle_period
        self._max_blocked_repeats = max_blocked_repeats

        self._tools: dict[str, Callable[..., str]] = {}
        self._schemas: dict[str, ToolSchema] = {}

        # Estado conversacional (M2): persiste entre llamadas a `run`.
        self._history: list[dict[str, Any]] = []
        self._last_user_index: int | None = None

    def register_tool(
        self,
        tool: Callable[..., str],
        schema: ToolSchema,
    ) -> None:
        """Registra una herramienta callable junto a su esquema.

        El esquema suele obtenerse con `ToolSchema.from_callable(fn)`. En
        `run`, pasá `tools=list(self._schemas.values())`; el cliente LLM
        aplica `to_llm_spec()` al llamar al proveedor.

        El callable se invoca con kwargs que coinciden con la firma.
        Debe devolver una cadena.

        Las Tools y esquemas no son mas que una array asociativo con el nombre del schema como key y la tool (callable) como value
        """
        self._tools[schema.name] = tool
        self._schemas[schema.name] = schema

    # ------------------------------------------------------------------
    # Gestión de historial (M2): ventana deslizante con recencia garantizada
    # ------------------------------------------------------------------

    def _windowed_messages(self) -> list[dict[str, Any]]:
        """Recorta `self._history` a `max_history_messages` para enviar al LLM.

        Estrategia: ventana deslizante sobre los últimos N mensajes. La
        invariante que nunca se rompe es que el último mensaje de usuario
        (`self._last_user_index`) siempre queda incluido, aun si eso
        significa recortar más mensajes "de cola" (tool/assistant
        posteriores) de los que la ventana normal descartaría. Además,
        evitamos que la ventana arranque con un mensaje `role: tool`
        huérfano (su `tool_call` correspondiente quedó fuera de la
        ventana), lo cual rompe proveedores reales como Bedrock
        (`ValidationException: toolResult blocks exceed toolUse blocks of
        previous turn` — visto en producción con `max_iterations` alto,
        ver INFORME_M3.md). Ese chequeo tiene que aplicarse tanto al
        recorte simple como a la cola que se ancla después del mensaje de
        usuario: un slice de cola puede arrancar en medio de un grupo
        `assistant(tool_calls=[...])` + sus respuestas `tool`, dejando un
        huérfano en `keep_after[0]` que un chequeo sobre `window[0]` no ve
        (ahí `window[0]` es el mensaje de usuario anclado, no el huérfano).
        """
        history = self._history
        cap = max(1, self._max_history_messages)

        if len(history) <= cap:
            window = list(history)
        else:
            last_user_idx = self._last_user_index
            if last_user_idx is None:
                last_user_idx = len(history) - 1
            tail_start = len(history) - cap

            if last_user_idx >= tail_start:
                window = history[tail_start:]
            else:
                # El mensaje de usuario más reciente quedaría fuera de la
                # ventana "natural": lo anclamos y completamos con los
                # mensajes más recientes posteriores a él que entren en el
                # presupuesto restante.
                after_user = history[last_user_idx + 1 :]
                keep_after = after_user[-(cap - 1) :] if cap > 1 else []
                while keep_after and keep_after[0].get("role") == "tool":
                    keep_after = keep_after[1:]
                window = [history[last_user_idx]] + keep_after

        while len(window) > 1 and window[0].get("role") == "tool":
            window = window[1:]
        return window

    # ------------------------------------------------------------------
    # Resiliencia: reintentos ante fallos transitorios
    # ------------------------------------------------------------------

    def _chat_with_retry(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None,
        system: str | None,
    ):
        attempts = 0
        while True:
            try:
                return self._llm.chat(messages=messages, tools=tools, system=system)
            except Exception as exc:
                attempts += 1
                if not _is_transient_error(exc) or attempts > self._max_llm_retries:
                    raise
                time.sleep(self._retry_backoff_seconds * attempts)

    def _is_looping(self, steps: list[AgentStep], name: str, arguments_json: str) -> bool:
        """True si ejecutar `(name, arguments_json)` ahora repetiría, una vez
        más, un ciclo de resultados idénticos que ya se vio
        `max_consecutive_repeats` veces seguidas.

        Generaliza a cualquier período de 1 a `max_cycle_period`, no solo
        una acción idéntica repetida (período 1): un agente puede repetir
        un *bloque* de varias acciones distintas en el mismo orden (p. ej.
        re-examinar la misma lista de objetos una y otra vez, ver
        `REENTREGA.md` sección 5.2).

        **Compara `(tool_name, tool_input, tool_output, error)` de los pasos
        ya ejecutados, no solo `(tool_name, tool_input)`** — la primera
        versión de este método solo miraba la llamada, asumiendo que
        "misma tool + mismos argumentos ⇒ mismo resultado" en este mundo
        determinístico. Eso es cierto para tools de solo lectura
        (`examine`), pero **no** para `go`: dos `go(direction="sur")`
        seguidos pueden ser legítimos y dar resultados distintos si cada
        uno te deja en una sala distinta (backtracking por una cadena
        lineal de salas, exactamente lo que pide `backtracking-vault` por
        diseño) — encontrado en la práctica bloqueando ese caso real
        (`REENTREGA.md`, sección 5.7). Exigir que los pasos ya ejecutados
        tengan además el *mismo resultado* entre sí antes de bloquear el
        intento actual corrige eso: si el resultado cambió entre llamadas
        idénticas, hay progreso real y no se bloquea; si no cambió, sí se
        bloquea, como antes.

        Solo se exige el resultado en los pasos *ya ejecutados* del ciclo
        (`max_consecutive_repeats` copias completas del bloque de período
        `p`); el intento actual todavía no tiene resultado, así que se
        compara únicamente por `(tool_name, tool_input)` contra lo que el
        ciclo ya visto predice como próxima llamada.

        Los pasos que ya fueron bloqueados por este mismo mecanismo
        (`_LOOP_BLOCKED_MARKER` en su `error`) se excluyen del historial
        antes de buscar el patrón: no son una ejecución real, así que no
        deben "romper" un ciclo genuino ni contar como parte de él —
        sin este filtro, el primer bloqueo cambia la firma del paso
        siguiente (`tool_output=None` en vez del resultado real) y el
        intento *después* de un bloqueo dejaba de verse como parte del
        ciclo, permitiendo que se re-ejecutara la tool real una vez más
        antes de volver a bloquear (oscilando en vez de bloquear de forma
        sostenida).
        """
        history = [
            (s.tool_name, s.tool_input, s.tool_output, s.error)
            for s in steps
            if not (s.tool_output is None and s.error and _LOOP_BLOCKED_MARKER in s.error)
        ]
        n = self._max_consecutive_repeats
        for period in range(1, self._max_cycle_period + 1):
            block_len = period * n
            if len(history) < block_len:
                continue
            tail = history[-block_len:]
            cycle = tail[:period]
            if not all(tail[i] == cycle[i % period] for i in range(block_len)):
                continue
            expected_name, expected_args, _, _ = cycle[0]
            if name == expected_name and arguments_json == expected_args:
                return True
        return False

    def _execute_tool(self, name: str, arguments_json: str) -> tuple[str | None, str | None]:
        """Ejecuta una tool registrada. Devuelve `(tool_output, error)`.

        Reintenta fallos transitorios; cualquier otro error (herramienta
        desconocida, JSON inválido, o una excepción propia de la tool como
        las de validación de `simple_calc`/`leer_archivo`) se devuelve tal
        cual como `error` accionable, sin romper el bucle del agente.
        """
        if name not in self._tools:
            disponibles = ", ".join(sorted(self._tools)) or "(ninguna)"
            return None, f"Herramienta desconocida: '{name}'. Herramientas disponibles: {disponibles}."

        try:
            kwargs = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            return None, f"Los argumentos para '{name}' no son JSON válido: {exc}"

        attempts = 0
        while True:
            try:
                result = self._tools[name](**kwargs)
                return str(result), None
            except Exception as exc:
                attempts += 1
                if _is_transient_error(exc) and attempts <= self._max_tool_retries:
                    time.sleep(self._retry_backoff_seconds * attempts)
                    continue
                return None, str(exc)

    # ------------------------------------------------------------------
    # Modo planner (M3, experimento "planner explícito vs. ReAct puro")
    # ------------------------------------------------------------------

    def _plan_subgoals(self, user_message: str) -> str:
        """Pide un plan de sub-metas vía `structured_call` y lo antepone al
        mensaje de usuario original.

        Aislado de `self._history` (mismo mecanismo que `structured_call`
        siempre usa) para que la fase de planificación no contamine el
        historial que después ve el bucle ReAct con una conversación
        distinta a la que el usuario mandó. Si el planner no logra producir
        un plan válido (`StructuredOutputError`, p. ej. el modelo no coopera
        tras los reintentos de reparación), se degrada a ReAct puro sobre el
        mensaje original en vez de romper `run`.
        """
        plan_prompt = (
            "Sos un planner. No ejecutes ninguna acción vos mismo: tu único trabajo "
            "es descomponer el siguiente objetivo en una lista ordenada de sub-metas "
            "concretas y verificables, en el orden en que un agente ejecutor debería "
            f"perseguirlas.\n\nObjetivo: {user_message}"
        )
        try:
            plan = self.structured_call(plan_prompt, _Plan)
        except StructuredOutputError:
            return user_message

        plan_text = "\n".join(f"{i}. {sg}" for i, sg in enumerate(plan.subgoals, start=1))
        return (
            f"{user_message}\n\n"
            "Plan de sub-metas sugerido (perseguilas en este orden salvo que lo que "
            "vayas descubriendo indique lo contrario):\n"
            f"{plan_text}"
        )

    def _triage(self, user_message: str) -> str:
        """Evalúa la complejidad aparente del objetivo y decide, en una sola
        llamada estructurada, si conviene anteponer un plan de sub-metas y/o
        recomendar delegar la exploración a `explorar_sala` — capa
        adaptativa (`adaptive=True`).

        A diferencia de `_plan_subgoals` (que siempre planifica cuando
        `planner=True`), acá la decisión de *si* planificar también sale del
        modelo, no de un flag externo fijo. Mismo mecanismo de
        `structured_call` aislado del historial; mismo contrato de
        degradación silenciosa ante `StructuredOutputError`: nunca rompe
        `run`, corre ReAct puro sobre el mensaje original si el triage
        falla.

        La decisión de exploración **poda** una de las dos rutas en vez de
        solo recomendarla como texto — encontrado en la práctica
        (`INFORME_M3.md`, sección 4.6): cuando `agent_mode="adaptive"`
        registra ambas rutas a la vez (`look`/`examine` directas y
        `explorar_sala` delegada), dejarlas *siempre* disponibles le daba
        al modelo una salida constante para "explorar una vez más" en vez
        de comprometerse a actuar — un trial de `backtracking-vault` gastó
        los 100 pasos completos alternando entre las dos sin un solo
        `take`/`use`/`go`. Si ambas rutas están registradas, el triage
        elimina de `self._tools`/`self._schemas` la que no recomendó, así
        que a partir de ahí el modelo ya no tiene la opción de alternar. Si
        solo una ruta está registrada (p. ej. `agent_mode="subagent"` o
        `"flat"` puros), no hay nada que podar — la recomendación queda
        solo como texto, o se omite si la ruta recomendada ni siquiera
        existe.
        """
        triage_prompt = (
            "Sos un evaluador de complejidad, no un ejecutor: no realices ninguna "
            "acción vos mismo. A partir del siguiente objetivo, decidí (a) si "
            "conviene anteponer un plan explícito de sub-metas antes de actuar, y "
            "(b) si conviene delegar la exploración detallada de cada sala a una "
            "herramienta separada en vez de examinar todo directamente. Basate "
            "solo en la complejidad aparente del objetivo (cuántas salas u "
            "objetos menciona, si hay dependencias de orden), no en cómo "
            f"resolverlo.\n\nObjetivo: {user_message}"
        )
        try:
            triage = self.structured_call(triage_prompt, _Triage)
        except StructuredOutputError:
            return user_message

        augmented = user_message
        if triage.plan_needed and triage.subgoals:
            plan_text = "\n".join(f"{i}. {sg}" for i, sg in enumerate(triage.subgoals, start=1))
            augmented += (
                "\n\nPlan de sub-metas sugerido (perseguilas en este orden salvo "
                "que lo que vayas descubriendo indique lo contrario):\n"
                f"{plan_text}"
            )

        has_direct = any(name in self._tools for name in _DIRECT_EXPLORATION_TOOLS)
        has_delegated = _DELEGATED_EXPLORATION_TOOL in self._tools

        if has_direct and has_delegated:
            # Ambas rutas registradas (agent_mode="adaptive"): podar la que
            # el triage no recomendó, no solo sugerirla.
            if triage.delegate_exploration_needed:
                for name in _DIRECT_EXPLORATION_TOOLS:
                    self._tools.pop(name, None)
                    self._schemas.pop(name, None)
                augmented += (
                    "\n\nEste escenario parece tener suficientes salas u objetos "
                    "como para que convenga delegar la exploración: a partir de "
                    "ahora solo tenés disponible `explorar_sala` para investigar "
                    "cada sala, `look`/`examine` ya no están disponibles."
                )
            else:
                self._tools.pop(_DELEGATED_EXPLORATION_TOOL, None)
                self._schemas.pop(_DELEGATED_EXPLORATION_TOOL, None)
                augmented += (
                    "\n\nEste escenario parece acotado: a partir de ahora "
                    "explorá cada sala directamente con `look`/`examine`, "
                    "`explorar_sala` ya no está disponible."
                )
        elif triage.delegate_exploration_needed and has_delegated:
            # Solo la ruta delegada está registrada (p. ej.
            # agent_mode="subagent"): no hay nada que podar, pero reforzar
            # la recomendación como texto sigue siendo útil.
            augmented += (
                "\n\nEste escenario parece tener suficientes salas u objetos "
                "como para que convenga delegar la exploración detallada de "
                "cada sala a la herramienta `explorar_sala` en vez de examinar "
                "todo vos mismo."
            )
        return augmented

    def _reflect(self, steps: list[AgentStep]) -> str | None:
        """Diagnóstico genérico de estancamiento (`reflect_on_stall=True`).

        Se dispara desde `run` cuando `_stall_streak` alcanza
        `stall_window` pasos sin novedad seguidos. A diferencia de
        `remind_pending_failures` (repite el error tal cual) o de
        `_is_looping` (corta ejecuciones repetidas en ráfaga, sin razonar
        sobre ellas), acá se le pide al propio modelo que mire el resumen
        de resultados recientes y explique qué está fallando — cubre tanto
        reintentos espaciados de la misma acción como "consiguió algo y
        no lo usó", ninguno de los dos con un patrón de texto fijo que
        reconocer desde afuera (`INFORME_M3.md`, sección 4.13).

        Mismo contrato de degradación silenciosa que `_plan_subgoals`/
        `_triage`: ante `StructuredOutputError` devuelve `None` (no hay
        sugerencia esa vez) en vez de romper `run`.
        """
        recent = steps[-self._stall_window :]
        recap = "\n".join(f"- {s.tool_name}({s.tool_input}) -> {s.error or s.tool_output}" for s in recent)
        prompt = (
            "Sos un evaluador externo, no un ejecutor: no realices ninguna acción vos "
            f"mismo. Un agente lleva {len(recent)} pasos sin progreso real — mirá sus "
            f"acciones y resultados más recientes:\n{recap}\n\n"
            "Diagnosticá en una oración por qué no está progresando (qué se repite, o "
            "qué consiguió pero no usó), y sugerí una próxima acción concreta y "
            "distinta de lo que se viene repitiendo."
        )
        try:
            reflection = self.structured_call(prompt, _Reflection)
        except StructuredOutputError:
            return None
        return f"{reflection.diagnosis} Sugerencia: {reflection.next_action_hint}"

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> AgentResult:
        """Ejecuta el bucle del agente hasta una respuesta final o `max_iterations`.

        M2: llamadas sucesivas sobre la misma instancia continúan la misma
        conversación (`self._history` persiste). En cada llamada a `chat`
        se envía `self._windowed_messages()`, que jamás supera
        `max_history_messages` y siempre conserva el último mensaje de
        usuario. Los tokens reportados por cada `LLMResponse` de esta
        llamada a `run` se acumulan en el `AgentResult` devuelto.

        M3 (`planner=True`): antes de la primera llamada de una conversación,
        el mensaje de usuario efectivo se aumenta con un plan de sub-metas
        (ver `_plan_subgoals`). Solo ocurre una vez por instancia: llamadas
        sucesivas a `run` sobre la misma conversación no vuelven a planificar.

        M3 (`adaptive=True`, tiene precedencia sobre `planner`): en vez de
        planificar siempre, la primera llamada dispara una fase de *triage*
        (ver `_triage`) donde el propio modelo decide, según la complejidad
        aparente del objetivo, si conviene planificar y/o delegar la
        exploración. También ocurre una única vez por instancia.
        """
        if not self._planned:
            self._planned = True
            if self._adaptive:
                user_message = self._triage(user_message)
            elif self._planner:
                user_message = self._plan_subgoals(user_message)

        self._history.append({"role": "user", "content": user_message})
        self._last_user_index = len(self._history) - 1

        steps: list[AgentStep] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        tools = list(self._schemas.values()) if self._schemas else None
        consecutive_blocks = 0

        for _ in range(self._max_iterations):
            messages = self._windowed_messages()
            if self._remind_pending_failures and self._pending_failures:
                # Transitorio: se agrega solo a la lista local que ve esta
                # llamada, nunca a `self._history` — así no se persiste ni
                # se cuenta contra `max_history_messages`, pero reaparece en
                # cada turno mientras el fallo siga sin resolverse (ver
                # docstring de `remind_pending_failures`).
                recent = list(self._pending_failures.items())[-_MAX_PENDING_FAILURE_REMINDERS:]
                reminder_lines = "\n".join(f"- {key}: {failure}" for key, failure in recent)
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Recordatorio — estos intentos fallaron antes y siguen sin "
                            "resolverse (puede que ya no aparezcan en tu historial "
                            "reciente, pero la causa del error sigue sin cambiar):\n"
                            f"{reminder_lines}\n"
                            "No los repitas tal cual: resolvé la causa antes de "
                            "reintentarlos."
                        ),
                    },
                ]
            if self._reflect_on_stall and self._active_reflection_hint:
                # Transitorio y de un solo uso: se agrega al próximo turno y
                # se limpia acá mismo, se haya usado o no — si el
                # estancamiento sigue, `_stall_streak` vuelve a acumularse y
                # dispara una reflexión nueva más adelante (ver `_reflect`).
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Reflexión automática — no se detectó progreso real en los "
                            f"últimos {self._stall_window} pasos:\n{self._active_reflection_hint}"
                        ),
                    },
                ]
                self._active_reflection_hint = None
            try:
                response = self._chat_with_retry(messages=messages, tools=tools, system=self._system)
            except Exception as exc:
                return AgentResult(
                    answer="",
                    steps=steps,
                    error=str(exc),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            input_tokens = _accumulate(input_tokens, response.input_tokens)
            output_tokens = _accumulate(output_tokens, response.output_tokens)

            if not response.tool_calls:
                self._history.append({"role": "assistant", "content": response.content or ""})
                return AgentResult(
                    answer=response.content or "",
                    steps=steps,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            self._history.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {"id": tc.id, "function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in response.tool_calls
                    ],
                }
            )

            for tool_call in response.tool_calls:
                looping = self._is_looping(steps, tool_call.name, tool_call.arguments)
                if looping:
                    consecutive_blocks += 1
                    tool_output = None
                    error = (
                        f"'{tool_call.name}' con estos argumentos ({tool_call.arguments}) "
                        f"{_LOOP_BLOCKED_MARKER} en los últimos pasos "
                        "(la misma acción, o el mismo bloque de acciones, en el mismo orden) — el "
                        "resultado va a ser igual, no se ejecutó de nuevo. No lo repitas: cambiá "
                        "de estrategia (otro ítem, otro objetivo, u otra herramienta) antes de "
                        "seguir."
                    )
                else:
                    consecutive_blocks = 0
                    tool_output, error = self._execute_tool(tool_call.name, tool_call.arguments)
                    if self._remind_pending_failures:
                        failure_key = f"{tool_call.name}:{tool_call.arguments}"
                        # Mismo criterio que `eval/failure_modes.py::_step_failed`:
                        # varias tools de `mia_world` señalan un fallo devolviendo
                        # un string `"Error: ..."` como `tool_output` normal en vez
                        # de lanzar, así que un fallo "suave" también cuenta.
                        is_failure = error is not None or (tool_output is not None and tool_output.startswith("Error:"))
                        if is_failure:
                            self._pending_failures[failure_key] = error if error is not None else tool_output
                        else:
                            self._pending_failures.pop(failure_key, None)
                steps.append(
                    AgentStep(
                        tool_name=tool_call.name,
                        tool_input=tool_call.arguments,
                        tool_output=tool_output,
                        error=error,
                    )
                )
                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_output if error is None else error,
                    }
                )

                if self._reflect_on_stall:
                    signature = (tool_call.name, tool_call.arguments, tool_output, error)
                    if signature in self._seen_step_signatures:
                        self._stall_streak += 1
                    else:
                        self._seen_step_signatures.add(signature)
                        self._stall_streak = 0
                    if self._stall_streak >= self._stall_window:
                        self._active_reflection_hint = self._reflect(steps)
                        self._stall_streak = 0

                if looping and consecutive_blocks > self._max_blocked_repeats:
                    # Bloquear el intento no obligó al modelo a cambiar de estrategia:
                    # siguió pidiendo la misma acción/ciclo ya bloqueado. Cortar acá en
                    # vez de agotar `max_iterations` insistiendo con algo que ya
                    # sabemos que no va a ejecutarse (ver REENTREGA.md, sección 5.4/5.5).
                    return AgentResult(
                        answer="",
                        steps=steps,
                        error=(
                            f"Se cortó la ejecución: la misma acción o ciclo de acciones quedó "
                            f"bloqueado por detección de ciclos {consecutive_blocks} veces seguidas "
                            "sin que el agente cambiara de estrategia ni se ejecutara ninguna tool "
                            "real en el medio."
                        ),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

        return AgentResult(answer="", steps=steps, input_tokens=input_tokens, output_tokens=output_tokens)

    # ------------------------------------------------------------------
    # Salida estructurada (M2)
    # ------------------------------------------------------------------

    def structured_call(
        self,
        prompt: str,
        schema: Any,
        max_repair_attempts: int = 2,
    ) -> Any:
        """Pide al LLM una respuesta validada contra `schema` vía `final_result`.

        Conversación aislada (no comparte `self._history`): en cada
        llamada a `chat` se ofrece únicamente la tool sintética
        `final_result` (`tools=[final_result_tool_schema(schema)]`).
        Termina cuando llega un `tool_call` a `final_result` cuyos
        argumentos validan contra `schema`. Si el modelo responde con
        texto libre, invoca otra tool, manda JSON inválido o argumentos
        que no validan, se agrega contexto de reparación y se reintenta
        hasta `max_repair_attempts` veces. Agotados los reintentos,
        levanta `StructuredOutputError`.
        """
        tool_schema = final_result_tool_schema(schema)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        last_error: str | None = None
        attempt = 0
        while attempt <= max_repair_attempts:
            response = self._chat_with_retry(messages=messages, tools=[tool_schema], system=self._system)

            final_call = next(
                (tc for tc in response.tool_calls if tc.name == FINAL_RESULT_TOOL_NAME),
                None,
            )

            if final_call is None:
                last_error = (
                    f"Debés invocar la herramienta '{FINAL_RESULT_TOOL_NAME}' (y solo esa) "
                    "para responder; no respondas con texto libre ni con otra herramienta."
                )
                messages.append({"role": "assistant", "content": response.content or ""})
                messages.append({"role": "user", "content": f"Formato inválido: {last_error}"})
                attempt += 1
                continue

            assistant_msg = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {"id": final_call.id, "function": {"name": final_call.name, "arguments": final_call.arguments}}
                ],
            }

            try:
                args = json.loads(final_call.arguments) if final_call.arguments else {}
            except json.JSONDecodeError as exc:
                last_error = f"Los argumentos de '{FINAL_RESULT_TOOL_NAME}' no son JSON válido: {exc}"
                messages.append(assistant_msg)
                messages.append({"role": "tool", "tool_call_id": final_call.id, "content": last_error})
                attempt += 1
                continue

            try:
                return schema.model_validate(args)
            except (ValidationError, TypeError) as exc:
                last_error = f"Los argumentos no cumplen el schema esperado: {exc}"
                messages.append(assistant_msg)
                messages.append({"role": "tool", "tool_call_id": final_call.id, "content": last_error})
                attempt += 1
                continue

        raise StructuredOutputError(
            f"No se pudo obtener una respuesta estructurada válida de '{FINAL_RESULT_TOOL_NAME}' "
            f"tras {max_repair_attempts} reintento(s) de reparación. Último error: {last_error}"
        )
