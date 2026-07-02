# Informe — Milestone 1

## Diagrama de arquitectura

### 
<img src="./doc/diagrama_1.svg" alt="Arquitectura" width="600">



El `run` itera: LLM decide → si pide `tool_calls`, el agente ejecuta los callables registrados → el resultado se vuelca como mensaje `role: "tool"` → se vuelve a invocar `chat`. Termina cuando el LLM responde solo texto, o al alcanzar `max_iterations`.

## Diseño de la interfaz de herramientas

- **`ToolSchema.from_callable(fn)`**: inspecciona la firma del callable (vía `get_type_hints` + `inspect.signature`) y construye un modelo Pydantic dinámico con `create_model`. De ahí deriva el JSON Schema de parámetros (`model.model_json_schema()`). No escribimos JSON Schema a mano en ningún lado.
- **`Annotated[tipo, Field(description=...)]`**: cada parámetro de la tool se anota así para que el `Field.description` quede embebido en el JSON Schema (`properties.<param>.description`), guiando al LLM sobre qué pasar en cada argumento.
- **Docstring de la función**: se usa tal cual (`inspect.getdoc` + `cleandoc`) como `ToolSchema.description` — es la única fuente de verdad que el LLM ve para entender qué hace la herramienta.
- **`register_tool(tool, schema)`**: guarda dos diccionarios paralelos indexados por `schema.name`: `self._tools[name] = tool` (el callable, para ejecutarlo) y `self._schemas[name] = schema` (el `ToolSchema`, para exponerlo al LLM). Nunca se mezclan: `chat(tools=...)` solo recibe esquemas, jamás callables.
- **`chat(tools=list(self._schemas.values()))`**: en cada llamada del loop se pasa la lista completa de esquemas registrados (o `None` si no hay ninguno). El `LLMClient` fijo es agnóstico de cómo se generaron esos esquemas.
- **Qué hace el `LLMClient` con cada esquema**: internamente llama a `schema.to_llm_spec()` (dict con `name`/`description`/`parameters`) y cada proveedor lo envuelve en su formato nativo — `OllamaProvider._wrap_tool_spec` produce `{"type": "function", "function": {...}}`; `BedrockProvider._wrap_tool_spec` produce `{"toolSpec": {...}}` para la API Converse. El agente nunca ve ese formato nativo, solo trabaja con `ToolSchema`/`LLMResponse` normalizados.

## Cómo termina el bucle

`MyAgent.run` itera hasta `self._max_iterations` (default `10`). En cada vuelta:

1. Llama a `chat(messages, tools, system)`.
2. Si la respuesta **no** tiene `tool_calls` → corta inmediatamente y devuelve `AgentResult(answer=content, steps, input_tokens, output_tokens)`. Esta es la única salida "exitosa" en M1.
3. Si tiene `tool_calls` → agrega el mensaje `role: "assistant"` con esos `tool_calls` al historial, ejecuta cada tool (parseando `arguments` con `json.loads`), agrega un mensaje `role: "tool"` por cada resultado, y vuelve al paso 1.

**Qué pasa al alcanzar el límite**: si se agotan las `max_iterations` sin que el LLM devuelva una respuesta final en texto (p. ej. porque entra en un loop pidiendo tools repetidamente), el `for` termina sin lanzar excepción y la función devuelve `AgentResult(answer="", steps=steps)` — con todos los `AgentStep` acumulados hasta ese punto. Nunca se propaga una excepción ni se devuelve `None`.

`max_history_messages` se acepta en el constructor pero en M1 **no se aplica** (la lista de mensajes crece sin recorte); su uso real para limitar la longitud de la conversación es contrato de M2, junto con la persistencia de estado entre llamadas a `run`.

## Limitaciones conocidas

- **`run` es stateless entre llamadas**: cada invocación arranca el historial desde cero con el `user_message` recibido; no hay memoria entre llamadas sucesivas (eso es M2).
- **`max_history_messages` no se respeta en M1**: una conversación con muchas tool_calls puede generar una lista de mensajes arbitrariamente larga dentro de un mismo `run`.
- **Sin `structured_call`**: el método está como stub (`NotImplementedError`); es contrato de M2.
- **Tool de Markowitz permite posiciones en corto**: la solución de forma cerrada no restringe `w ≥ 0`; una versión long-only requeriría programación cuadrática (scipy, no incluido en las dependencias).
- **`leer_archivo` está acotado al directorio `archivos/`** y rechaza rutas absolutas, pero no valida symlinks que escapen del directorio.
- **Errores de tool desconocida o de ejecución no detienen el loop**: quedan registrados como `AgentStep` con `error` no nulo y el contenido del error se devuelve al LLM como mensaje `tool`, pero si el LLM insiste en la misma tool inválida, el único freno es `max_iterations`.

---

# Tool: Optimizador de Carteras (Markowitz)

## Qué hace

`optimizar_portfolio_markowitz` (en [student_framework/tools/portfolio_markowitz.py](student_framework/tools/portfolio_markowitz.py)) recibe series de retornos históricos por activo y calcula el **portfolio de varianza mínima** según el modelo de Markowitz: los pesos que minimizan el riesgo total de la cartera, sujetos a que sumen 1.

Usa la solución de forma cerrada:

```
w = Σ⁻¹ · 1 / (1ᵀ · Σ⁻¹ · 1)
```

donde `Σ` es la matriz de covarianza muestral de los retornos.

**Limitación conocida:** no restringe los pesos a ser positivos, por lo que permite posiciones en corto (`w` puede tener componentes negativas). La versión long-only requeriría programación cuadrática (no incluida en las dependencias actuales).

## Requisitos previos

```bash
cd /Users/carbonecar/maestria_ia/agentes_autonomos/tp_mia_agentes_2026
source .venv/bin/activate
pip install -r requirements.txt   # incluye numpy>=1.26.0
```

Para ejecutar vía el agente (no para los tests, que usan mocks) hace falta un proveedor LLM activo:

```bash
# Ollama local
export OLLAMA_HOST="http://localhost:11434"
export OLLAMA_MODEL="llama3.1"
ollama serve   # en otra terminal, si no está corriendo
```

## Ejecución directa de la tool (sin LLM)

Útil para validar el cálculo en aislamiento, sin pasar por el agente:

```bash
PYTHONPATH=. python3 -c "
from student_framework.tools.portfolio_markowitz import optimizar_portfolio_markowitz
print(optimizar_portfolio_markowitz({
    'AAPL': [0.02, -0.01, 0.015, 0.005, -0.005, 0.01, 0.0, 0.02],
    'MSFT': [0.015, 0.0, 0.01, 0.008, -0.002, 0.012, 0.005, 0.018],
    'GOOG': [-0.01, 0.02, -0.005, 0.01, 0.0, -0.008, 0.015, 0.005],
}))
"
```

Salida esperada (JSON):

```json
{"pesos": {"AAPL": -0.172198, "MSFT": 0.867702, "GOOG": 0.304496}, "retorno_esperado": 0.007002, "riesgo_portfolio": 0.004181}
```

## Ejecución vía el agente (CLI)

El agente expone la tool al LLM, que decide cuándo invocarla a partir de un mensaje en lenguaje natural:

```bash
PYTHONPATH=. OLLAMA_HOST=http://localhost:11434 OLLAMA_MODEL=llama3.1 \
python3 -m mia_agents.cli run --module student_framework --message \
"Tengo retornos históricos de tres activos: AAPL=[0.02,-0.01,0.015,0.005,-0.005,0.01,0.0,0.02], MSFT=[0.015,0.0,0.01,0.008,-0.002,0.012,0.005,0.018], GOOG=[-0.01,0.02,-0.005,0.01,0.0,-0.008,0.015,0.005]. ¿Cuáles son los pesos óptimos del portfolio de varianza mínima según Markowitz?"
```

El resultado (`AgentResult`) incluye:

- `answer`: la respuesta del LLM interpretando el resultado de la tool.
- `steps`: un `AgentStep` con `tool_name="optimizar_portfolio_markowitz"`, los `arguments` parseados y el `tool_output` (JSON crudo devuelto por la tool).

## Debug en VS Code

La configuración **"CLI: run agent"** en [.vscode/launch.json](.vscode/launch.json) ya trae `PYTHONPATH`, `OLLAMA_HOST` y `OLLAMA_MODEL` seteados. Para probar la tool de Markowitz desde el debugger, editar el campo `args` de esa configuración y reemplazar el `--message` por una consulta de portfolio como la del ejemplo anterior.

## Tests automáticos

La tool no tiene un test de conformidad dedicado (la suite fija de M1 cubre el contrato general del agente), pero corre dentro de la suite completa sin romper nada:

```bash
python3 -m pytest tests/conformance/test_m1.py
```
