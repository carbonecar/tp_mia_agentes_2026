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

from pydantic import ValidationError

from mia_agents.protocols import LLMClient
from mia_agents.tool_schema import FINAL_RESULT_TOOL_NAME, final_result_tool_schema
from mia_agents.types import AgentResult, AgentStep, ToolSchema


class StructuredOutputError(RuntimeError):
    """Se agotaron los reintentos de reparación en `structured_call`."""


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
        """
        self._llm = llm_client
        self._system = system_prompt
        self._max_iterations = max_iterations
        self._max_history_messages = max_history_messages
        self._max_llm_retries = max_llm_retries
        self._max_tool_retries = max_tool_retries
        self._retry_backoff_seconds = retry_backoff_seconds

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
        """
        self._history.append({"role": "user", "content": user_message})
        self._last_user_index = len(self._history) - 1

        steps: list[AgentStep] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        tools = list(self._schemas.values()) if self._schemas else None

        for _ in range(self._max_iterations):
            messages = self._windowed_messages()
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
                tool_output, error = self._execute_tool(tool_call.name, tool_call.arguments)
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
