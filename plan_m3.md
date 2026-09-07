# Plan de entrega — Milestone 3 (`ENUNCIADO_M3.md`)

## Contexto

`mia_world/` (mundo simulado tipo sala de escape) y `scenarios/` (8 escenarios
JSON de dificultad creciente) son FIJOS y ya están completos y testeados
(`tests/conformance/test_m3_world.py` y `test_m3_world_review.py` pasan sin
tocar nada). El agente de M1+M2 (`student_framework/agent.py`) también está
completo: bucle de tools, historial estatal con ventana deslizante
(`max_history_messages`), `structured_call` con `final_result`, reintentos
ante fallos transitorios y acumulación de tokens.

Lo que **falta** para M3 es puramente la parte "student work" que señala el
enunciado: **infraestructura de evaluación** (`eval/`, no existe todavía),
métricas, análisis de errores, experimentos, e informe. No hace falta tocar
`build_agent` de forma especial: el patrón para correr un escenario ya está
en `mia_world/cli.py::_cmd_run` — `build_agent()` fresco + `make_world_tools(world)`
registradas sobre esa instancia — y es el mismo patrón que va a reutilizar
`eval/run.py` por cada caso.

Decisiones ya tomadas con el usuario:
- Proveedor por defecto para las corridas que van al informe: **Bedrock
  (`amazon.nova-lite-v1:0`)**, ya configurado en `.env`. El runner debe
  seguir funcionando con Ollama vía `LLMClient.from_env()` sin cambios de
  código (ya es así), pero los números reportados en `INFORME.md` salen de
  Bedrock.
- **3 experimentos** (uno más que el mínimo pedido).

## Qué se construye

### 1. `eval/` — infraestructura de evaluación reproducible

```
eval/
├── __init__.py
├── run.py          # entry point CLI: `python eval/run.py [...]`
├── runner.py        # run_case() / run_suite(): ejecuta agente contra escenarios
├── metrics.py        # métricas cuantitativas + judge cualitativo
├── failure_modes.py  # categorización de errores
└── results/           # salidas versionadas (JSON por corrida + resumen)
```

- **`runner.py`**: por cada escenario, construye un agente nuevo con
  `build_agent(config)` (mismo mecanismo que ya usan los tests de
  conformidad para inyectar overrides), registra `make_world_tools(world)`
  sobre ese mundo (igual que `cli.py`), corre `agent.run(scenario.user_message)`,
  y captura: `AgentResult` completo (`steps`, `error`, tokens), tiempo de
  wall-clock, `check_goal(world, scenario.goal)`, y el número de tool-calls
  reales usados vs. el `optimal` de la tabla del enunciado (hardcodeada como
  constante en `metrics.py`, ya que no vive en el JSON del escenario).
  Soporta **N trials por escenario** (el LLM es no determinístico) y
  **overrides de config** (`max_history_messages`, `max_iterations`,
  `system_prompt`) para reutilizarse en baseline y en los 3 experimentos.
- **`run.py`**: CLI (`argparse`, mismo estilo que `mia_world/cli.py`) con
  flags `--scenarios` (lista o `all`), `--trials`, `--module` (default
  `student_framework`), `--out` (default `eval/results/`), `--label`
  (nombre de la corrida/experimento). Sin pasos manuales: una sola invocación
  deja JSON crudo por caso + un resumen (`summary_<label>.json` y una tabla
  Markdown lista para pegar en `INFORME.md`).
- Reutiliza `mia_world.cli._resolve_scenario` para aceptar id/dificultad/path
  igual que la CLI existente, evitando duplicar esa lógica.

### 2. Métricas (`eval/metrics.py`)

- **Cuantitativas**:
  - *Success rate* por escenario y por dificultad (`goal_achieved` de
    `check_goal`, la métrica confiable que pide el enunciado porque mira
    estado, no texto).
  - *Eficiencia*: `tool_calls_usados / optimal_calls` (tabla del enunciado)
    — mide si el agente encuentra la solución o "vagabundea".
  - *Costo/latencia*: tokens acumulados (`input_tokens`/`output_tokens`) y
    tiempo de wall-clock por caso — justificado porque Bedrock cobra por
    token y el enunciado lista "coste" y "latencia" como métricas válidas.
- **Cualitativa**: rúbrica vía LLM-as-judge, implementada reusando
  `structured_call` del propio framework (mismo agente, otra instancia) con
  un `pydantic.BaseModel` de 3 dimensiones (p.ej. `exploracion_dirigida`,
  `recuperacion_de_errores`, `uso_de_planificacion`, cada una 1–5 +
  justificación breve). Corre sobre la transcripción de `steps` de cada
  caso. Justificación: da señal donde `check_goal` es binario (p.ej. un
  agente puede fallar `office-sequence` por *casi* lograrlo en el orden
  correcto vs. divagar sin rumbo — la rúbrica lo distingue, el booleano no).

### 3. Análisis de errores (`eval/failure_modes.py`)

Categorizador que recorre `steps`/`error` y `event_log` de cada caso fallido
y etiqueta uno o más de:
- `max_iterations_agotado` (sin `goal_achieved`, sin `error`, loop lleno).
- `tool_call_alucinado` (`error` con "Herramienta desconocida" o ids
  inexistentes en `use`/`take`/`examine`).
- `accion_repetida_fallida` (mismo `(tool_name, tool_input)` con error 2+
  veces seguidas — indica que el agente no aprende del error).
- `desborde_de_contexto` (específico de `extreme-archive`: caída de
  disciplina de tool-calling tras examinar muchos expedientes — se detecta
  por steps con `tool_name is None` intercalados o respuestas de texto libre
  en medio del loop).
- `orden_de_secuencia_violado` (específico de escenarios con goal
  `sequence`, p.ej. `office-sequence`: goal parcialmente cumplido pero
  `check_goal` devuelve razón de orden).
- `perdida_de_mapa_multi_sala` (multi-sala: el agente vuelve a `go` hacia
  una sala ya visitada sin necesidad, o pide `take`/`examine` de un item de
  otra sala).

Salida: tabla resumen (categoría × escenario × conteo) que se pega en
`INFORME.md`.

### 4. Experimentos (3, todos como variantes de `runner.py`/`run.py`)

1. **Ventana de historial** (`max_history_messages`): chico (p.ej. 8) vs.
   default (50). Corre sobre toda la suite pero con foco en los multi-sala
   (`apartment-keys`, `office-sequence`, `vault-combination`,
   `backtracking-vault`) — el enunciado señala explícitamente que
   `apartment-keys` "pone a prueba la memoria de estado del M2".
2. **Estrategia de prompting** (`system_prompt`): genérico actual
   ("Eres un asistente útil") vs. uno que pide explícitamente descomponer
   el objetivo en sub-metas antes de actuar. Foco en `office-sequence`
   (goal `sequence`) — el enunciado lo plantea directamente como experimento
   "planner explícito vs. ReAct puro".
3. **Presupuesto de pasos** (`max_iterations`): default (10) vs. ajustado
   cerca del `optimal` de cada escenario (tabla del enunciado) — mide cuántos
   escenarios siguen resolviéndose bajo presión de eficiencia y cuáles
   dependían de margen extra para recuperarse de errores.

Cada experimento corre baseline vs. variante con el mismo `--trials`,
mismo set de escenarios, y se compara con las métricas de la sección 2.

### 5. Informe (`INFORME.md`)

Se agrega una sección nueva `# Informe — Milestone 3` al final del archivo
existente (mismo patrón que M1/M2, que ya conviven en el mismo documento),
con las 5 subsecciones obligatorias del enunciado:
1. Aproximación (qué se reusó de M1+M2 sin cambios, qué se agregó solo para
   evaluación).
2. Métricas (qué/por qué/cómo, sección 2 de este plan).
3. Resultados (tabla de success rate + eficiencia + costo por escenario/
   dificultad, generada por `eval/run.py`).
4. Experimentos (los 3 de la sección 4, con tablas antes/después).
5. Limitaciones y próximos pasos (p.ej. rúbrica LLM-as-judge no
   determinística, extreme-archive como caso límite de contexto, etc.).

## Verificación

- `pytest tests/conformance/test_m3_world.py tests/conformance/test_m3_world_review.py`
  — confirma que no se rompió nada del scaffold fijo (no debería cambiar,
  solo se corre como smoke check).
- Smoke test manual antes de la corrida completa (paga):
  `python eval/run.py --scenarios easy medium --trials 1` — valida que el
  runner arma bien el agente, registra tools, escribe resultados, sin gastar
  de más en Bedrock.
- Corrida completa: `python eval/run.py --scenarios all --trials N` (baseline)
  + 3 corridas de experimento (`--label`s distintos) — quedan en
  `eval/results/` y alimentan los números del informe.
- Revisión visual de `eval/results/summary_*.json` / tabla Markdown antes de
  pegarla en `INFORME.md`.
