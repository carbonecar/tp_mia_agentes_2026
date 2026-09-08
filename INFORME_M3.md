# Informe — Milestone 3

> **Estado actual.** Este documento reemplaza a `INFORME_M3.md` (versión
> anterior), `resumen-informe-m3.md` y `REENTREGA.md`, unificados en un solo
> informe (ver nota al final de esta caja). Responde a la devolución
> recibida sobre la entrega original de M3, que señaló tres puntos:
>
> 1. El informe estaba corto de experimentos (solo uno terminado).
> 2. No había avances significativos en el *framework* (memoria semántica,
>    subagentes, planificación) — los experimentos se limitaban a prompt e
>    iteraciones.
> 3. Era confuso tener dos archivos de informe separados.
>
> Este documento resuelve los tres: agrega **planner explícito** y
> **subagentes (delegación de tools)** como extensiones reales de
> `student_framework/agent.py` (sección 4.3/4.4), agrega una tercera
> extensión de framework encontrada en el camino —**detección de ciclos en
> el loop del agente** (sección 4.5)—, y consolida todo en un único
> documento con las 5 secciones que pide `ENUNCIADO_M3.md`.
>
> Todas las corridas contra proveedor real usan Bedrock
> `amazon.nova-lite-v1:0`. Los números con `n=3` trials por escenario deben
> leerse con cautela frente a la varianza de un LLM no determinístico —se
> señala explícitamente cada vez que una lectura puntual no se pudo
> confirmar con más muestra.

## 1. Aproximación

### 1.1 Agente base — M1+M2 sin especializar

El agente que resuelve los escenarios de escape-room es exactamente el de
M1+M2 (`student_framework/agent.py`): mismo `run`, misma ventana deslizante
de historial, mismos reintentos ante fallos transitorios. Lo único que
cambia por caso es qué tools están registradas — las del mundo
(`mia_world.tools.make_world_tools`) se agregan sobre un agente construido
con `build_agent(config)`, igual que ya lo hacía `mia_world/cli.py`.

`build_agent` sigue registrando siempre las tools de M1 (`simple_calc`,
`leer_archivo`, `optimizar_portfolio_markowitz`) además de las del mundo —
no se filtran para M3, porque el enunciado no pide especializar
`build_agent`; queda como ruido conocido en el tool-list que ve el LLM.

### 1.2 Infraestructura de evaluación (`eval/`)

- **`eval/runner.py`** (`run_case`/`run_suite`): por cada escenario y
  trial, copia (`copy.deepcopy`) el `World` inicial (las tools lo mutan en
  sitio), construye un agente fresco, corre `agent.run(...)` envuelto en
  `try/except` (una excepción no debe abortar la suite — M1/M2 exige que
  `run` nunca lance) y captura `AgentResult`, tiempo de wall-clock,
  resultado de `check_goal` y el `event_log` del mundo. Instrumenta las
  tools ya registradas (`_instrument_goal_progress`) para reevaluar
  `check_goal` después de cada invocación y guardar
  `goal_achieved_at_step` (distinto de "pasos totales usados"). Gana
  `agent_mode: "flat" | "subagent"` (sección 1.3.2).
- **`eval/run.py`**: CLI reproducible (`python eval/run.py`). Resuelve
  escenarios por id, dificultad o `all`, acepta overrides de config
  (`--max-history-messages`, `--max-iterations`, `--system-prompt`/
  `--system-prompt-file`, `--planner`, `--agent-mode`, o un JSON arbitrario
  con `--config`) y un flag `--judge` opcional para la rúbrica cualitativa.
  Deja un JSON por caso más `summary.json`/`summary.md` en
  `eval/results/<label>/`.
- **`eval/metrics.py`** y **`eval/failure_modes.py`**: ver secciones 2 y 3.

**Harness agregado — timeout por caso** (`eval/runner.py::_case_time_limit`,
`run_case`/`run_suite` ganan `case_timeout_seconds`, `eval/run.py` gana
`--case-timeout-seconds`): motivado por un incidente real de esta entrega
(sección 4.4) donde un caso quedó colgado contra el proveedor de LLM y
obligó a matar el proceso completo a mano, perdiendo también los casos ya
corridos que no se habían guardado todavía. Antes de este harness,
`agent.run()` no tenía ningún límite propio más allá de `max_iterations` —
que no ayuda si lo que tarda es una sola llamada de red, no el número de
pasos. Implementado con `signal.setitimer(SIGALRM, ...)` (no un
hilo/proceso aparte) para poder interrumpir también una llamada de red
bloqueante, que es exactamente lo que pasó en el incidente real. Si un caso
excede el límite, ese caso puntual se marca como fallo
(`caso_timeout_abortado` en `eval/failure_modes.py`) y la suite sigue con
el resto — no hace falta matar el proceso ni perder los casos ya corridos.

Detalle no obvio encontrado al verificar con `MockLLMClient`: el
`AgentResult.error` del corte típicamente aparece dentro de
`agent_result.error`, no en `run_error` de más arriba, porque
`MyAgent.run()` atrapa *cualquier* excepción de la llamada al LLM (contrato
M1/M2 de "nunca lanza") y la vuelca ahí en vez de dejarla propagar — el
mismo mecanismo por el que `ciclo_escalado_abortado` (sección 1.3.3) tampoco
aparece en `run_error`. Y un hallazgo más sutil todavía: la primera versión
de la excepción se llamaba `CaseTimeoutError`, y el solo nombre de la clase
(sin importar el mensaje) hacía que
`student_framework/agent.py::_is_transient_error` la clasificara como fallo
transitorio de LLM (contiene el substring `"timeout"`) y la **reintentara**
en vez de dejarla propagar — el propio reintento del agente se tragaba el
corte del harness, y el caso terminaba de todas formas, solo que más tarde
de lo pedido. Renombrada a `CaseDeadlineExceeded` (ni la clase ni el mensaje
matchean ningún marcador de `_TRANSIENT_MARKERS`) para que se trate como
error permanente y el corte sea efectivo en el primer intento. Verificado
con `MockLLMClient` (un cliente que duerme más que el límite): el caso se
corta a tiempo, `run_suite` sigue normalmente con el siguiente caso, y un
caso rápido con un límite generoso no se ve afectado. Trade-off aceptado:
solo funciona en el hilo principal y en sistemas POSIX (usa `SIGALRM`); en
Windows, o si no se pasa `--case-timeout-seconds`, el caso corre sin límite,
igual que antes de este cambio.

Todo verificado de forma determinística con `MockLLMClient` scripteado
antes de gastar contra un proveedor real — criterio aplicado sin excepción
a lo largo de todo M3, incluidas las tres extensiones de framework de la
sección 1.3.

### 1.3 Extensiones de framework agregadas en esta entrega

De las opciones discutidas (memoria semántica/resumen, subagentes,
planificación explícita, detección de ciclos), se implementaron las tres
que más se diferencian de "ajustar un parámetro o el texto del prompt", y
que el propio `ENUNCIADO_M3.md` sugiere para `apartment-keys`/
`office-sequence`. Ninguna tocó `mia_world/` (scaffold fijo) ni las 3
líneas marcadas `NO CAMBIAR` en `student_framework/__init__.py`; las tres
quedan expuestas como overrides de `config` en `build_agent`
(`optional_keys_list`).

#### 1.3.1 Planner explícito

Nuevo parámetro `MyAgent(planner=True)`. En la primera llamada a `run()` de
una conversación, antes del loop ReAct habitual:

1. Se dispara una fase de planificación aislada vía `structured_call` (la
   misma pieza de M2 que usa `final_result` para salida validada) contra un
   schema nuevo `_Plan` (`subgoals: list[str]`, 3 a 8 sub-metas ordenadas).
2. El texto del plan se antepone al mensaje de usuario original (se
   aumenta, no se reemplaza), y ese mensaje aumentado arranca el historial
   y el loop ReAct de siempre.
3. Si el planner no logra un plan válido, se degrada silenciosamente a
   ReAct puro: un fallo del planner nunca rompe `run()`.
4. Solo planifica una vez por instancia (`self._planned`).

Deliberadamente no se tocó el loop ReAct en sí — la variable experimental
es únicamente "¿el mensaje que arranca la conversación trae un plan de
sub-metas, o no?".

#### 1.3.2 Subagentes — delegación de tools

Separa responsabilidades entre dos agentes en vez de un único loop
monolítico (`student_framework/tools/explorer_subagent.py`):

- **Explorador**: `MyAgent` con únicamente `look`/`examine` registradas y
  system prompt propio. Investiga la sala actual y devuelve un resumen en
  texto.
- **Actor**: registra `take`/`use`/`go` más una tool nueva,
  `explorar_sala(foco=None)`, en vez de `look`/`examine` directas.

`make_explorer_tool(llm_client, look_pair, examine_pair, world,
cost_sink=...)` arma la tool. Cada invocación *real* construye un
explorador nuevo (sin historial acumulado, reusa el mismo `llm_client` del
actor) — "real" porque cachea por firma de estado del `World`
(`_state_signature`): si nada cambió desde la última exploración con el
mismo `foco`, devuelve el mismo resumen sin gastar LLM. `foco` (opcional)
permite pedir una lectura profunda de *un* objeto puntual en vez de barrer
toda la sala de nuevo. Las líneas `Inventario:`/`Cerraduras:` del resumen
se recalculan siempre desde `world` (`_apply_ground_truth`), nunca se
confía en que el explorador las reporte bien — son datos 100% derivables.

**Costo oculto, medido explícitamente**: `mia_agents/types.py` documenta
que sub-agentes invocados por herramientas no se contabilizan en el
`AgentResult` de quien los invoca. `cost_sink` acumula `calls`/
`input_tokens`/`output_tokens` de cada corrida del explorador;
`eval/metrics.aggregate_explorer_cost` los suma y `eval/run.py` los
reporta aparte en `summary.md`/`summary.json`, para que la comparación de
costo entre modos sea honesta.

`eval/runner.py` gana `agent_mode: "flat" | "subagent"`; `eval/run.py`
gana `--agent-mode {flat,subagent}`.

#### 1.3.3 Detección de ciclos en el loop del agente

Extensión genérica de framework (no específica de subagentes, aplica igual
a `flat`) motivada por `accion_repetida_fallida`, el modo de fallo más
persistente de todo el proyecto. `MyAgent` gana tres parámetros:

- `max_consecutive_repeats: int = 2` y `max_cycle_period: int = 8`:
  `_is_looping(steps, name, arguments_json)` detecta si el intento actual
  completaría la repetición de un bloque de 1 a `max_cycle_period` llamadas
  ya visto `max_consecutive_repeats + 1` veces seguidas, comparando
  `(tool_name, tool_input, tool_output, error)` completo (no solo el
  nombre/argumentos — necesario porque tools como `go` dan resultados
  distintos con argumentos idénticos según el estado). Si detecta el
  patrón, no ejecuta la tool: le devuelve al modelo un mensaje correctivo
  explícito en su lugar.
- `max_blocked_repeats: int = 5`: si el bloqueo se sostiene más de
  `max_blocked_repeats` veces seguidas sin que se ejecute ninguna tool real
  en el medio, `run()` corta la ejecución y devuelve un `AgentResult.error`
  explícito en vez de seguir agotando `max_iterations` sin ninguna chance
  real de converger.

`eval/failure_modes.py` gana `ciclo_escalado_abortado` para distinguir este
corte deliberado de un fallo real del LLM/proveedor
(`fallo_llm_no_transitorio`).

#### 1.3.4 Capa adaptativa: decidir planificar/delegar según complejidad anticipada

Las tres extensiones anteriores se activan con una decisión externa y fija
(`planner=True`/`agent_mode="subagent"`, elegidos antes de correr el
agente, iguales para los 24 casos de una corrida). Esta capa reemplaza esa
decisión externa por una que el propio modelo hace, caso por caso, a
partir de la complejidad aparente del objetivo — sin necesitar dos
corridas separadas para comparar "con" y "sin".

`MyAgent(adaptive=True)` (precedencia sobre `planner` si ambos son
`True`): en la primera llamada a `run()` de una conversación, en vez de
planificar siempre o nunca, dispara una fase de **triage** —
`structured_call` aislado contra un schema nuevo `_Triage`
(`plan_needed: bool`, `subgoals: list[str]`, `delegate_exploration_needed:
bool`) — donde el modelo evalúa, a partir únicamente del mensaje inicial
(que en este dataset ya describe la sala/objetivo de partida), si conviene
anteponer un plan de sub-metas y/o recomendar delegar la exploración a
`explorar_sala`. Igual que el planner, se degrada silenciosamente a ReAct
puro si el triage no logra una salida estructurada válida.

Diseño, en su estado actual (v2, tras el fix de la sección 4.6 — la v1
original solo agregaba la recomendación como texto, sin tocar qué tools
están disponibles; ver más abajo por qué cambió):

- `agent_mode="adaptive"` en `eval/runner.py::_register_world_tools`
  registra **ambas rutas a la vez** (`look`/`examine` directas *y*
  `explorar_sala`), a diferencia de `"subagent"` (que solo registra
  `explorar_sala`, sin alternativa) o `"flat"` (solo las directas).
- Si ambas rutas quedan registradas, el triage no se limita a
  *recomendar* una — **poda** de `self._tools`/`self._schemas` la que no
  eligió: si `delegate_exploration_needed` es `True`, elimina
  `look`/`examine` y deja solo `explorar_sala`; si es `False`, elimina
  `explorar_sala` y deja `look`/`examine`. El mensaje aumentado avisa
  explícitamente cuál tool ya no está disponible. Si solo una ruta estaba
  registrada de entrada (`agent_mode="subagent"` o `"flat"` puros con
  `adaptive=True`), no hay nada que podar — la recomendación queda como
  texto nomás (subagent) o se omite del todo si la ruta recomendada ni
  siquiera existe (flat).

**Por qué se agregó la poda (no estaba en la v1 original)**: la primera
corrida contra Bedrock (v1, solo recomendación textual, ver más abajo) dio
58% y encontró un modo de fallo nuevo — con ambas rutas *siempre*
disponibles, un trial de `backtracking-vault` gastó los 100 pasos
completos alternando `explorar_sala`/`examine`/`look` sin un solo
`take`/`use`/`go`: tener una salida constante para "explorar una vez más"
le permitió al modelo posponer indefinidamente el momento de actuar. La
poda cierra esa salida en cuanto el triage decide, forzando al modelo a
comprometerse con una sola vía de información desde el principio de la
conversación.

`eval/run.py` gana `--adaptive` (activa `config["adaptive"]=True`,
independiente de `--agent-mode`, igual que `--planner`) y
`--agent-mode adaptive` (registra el toolset híbrido). El uso previsto es
combinar ambos: `--agent-mode adaptive --adaptive`.

Verificado con `MockLLMClient` (sin gastar nada), sobre las cinco
combinaciones relevantes: ambas rutas registradas + `delegate_needed=True`
poda `look`/`examine` y dice explícitamente que solo queda
`explorar_sala`; ambas registradas + `delegate_needed=False` poda
`explorar_sala` y dice que solo quedan `look`/`examine`; solo
`explorar_sala` registrada (combo con `agent_mode="subagent"`) no poda
nada, solo refuerza con texto; solo `look`/`examine` registradas (combo con
`agent_mode="flat"`) no agrega ningún texto ni poda nada;
`plan_needed`+`delegate_needed` ambos `True` conviven en el mismo triage
sin interferirse. Además: un triage que nunca invoca `final_result`
degrada a ReAct puro sin romper `run()`; una segunda llamada a `run()`
sobre la misma instancia no vuelve a triagear. Confirmado también a través
de `eval.runner._register_world_tools` con `agent_mode="adaptive"`: el
actor queda con `examine`, `explorar_sala`, `look`, `take`, `use`
registradas simultáneamente antes del triage (más las tools de M1), y el
`cost_sink` del explorador se sigue reportando aparte.

**Confirmado contra Bedrock (sección 4.7): el fix de poda dio peor, no
mejor** (42% vs. 58% de la v1 sin podar) — la causa no fue un bug de la
poda en sí, sino que expuso un sesgo del triage hacia recomendar delegar
(83% de los trials) que la poda vuelve irreversible. Ver sección 4.7 para
el análisis completo y sección 5 para la conclusión de este experimento.

#### 1.3.5 `consultar_mapa`: mapa de navegación determinístico (sin LLM)

Motivada por `perdida_de_mapa_multi_sala` — el modo de fallo multi-sala
más persistente de todo el proyecto — y por lo encontrado en las
secciones 4.6/4.7: buena parte de los fallos de `adaptive`/`subagent` en
escenarios multi-sala vienen de que el agente pierde el hilo de qué salas
ya visitó y qué salidas ya probó, algo que el prompt le pide sostener en
su propia prosa ("mantené una lista de salas visitadas...") sin éxito.

`student_framework/tools/room_graph.py` agrega `consultar_mapa()` (sin
argumentos): **no usa el LLM en ningún momento** — es una función pura de
`World`, en el mismo espíritu que `_apply_ground_truth` (sección 1.3.2)
pero para topología de salas en vez de inventario/cerraduras. Sin costo,
sin necesidad de caché.

Qué expone, cuidando de no filtrar información que el agente no tiene
realmente (`look()` ya revela todas las direcciones de salida de la sala
actual, pero nunca el destino de una salida hasta cruzarla):

- **Salas visitadas y camino recorrido** (con repeticiones — útil
  específicamente para hacer explícito el backtracking en escenarios como
  `backtracking-vault`), derivados de `world.event_log` (`"enter:<sala>"`).
- **Todas las salidas de cada sala visitada** (`room.exits`): siempre
  seguro de mostrar, es lo que `look` ya mostró al entrar.
- **El destino de una salida, solo si esa transición específica ya
  ocurrió** — inferido cruzando pares consecutivos del camino recorrido
  contra las salidas de la sala de origen. Si no se cruzó todavía, queda
  como "destino sin confirmar" (con el estado del gate si la salida está
  bloqueada), nunca se revela de antemano.

`eval/runner.py::_register_world_tools` gana `include_room_graph: bool =
False`, **independiente de `agent_mode`**: se agrega igual en `flat`,
`subagent` o `adaptive`, y solo si el escenario tiene navegación (mismo
chequeo que usa `make_world_tools` para decidir si registra `go`).
`eval/run.py` expone `--room-graph`. La independencia de `agent_mode` es
deliberada: permite correr el mismo experimento "con mapa" vs. "sin mapa"
sobre cualquiera de las tres arquitecturas ya comparadas en la sección
3.2, en vez de atarlo a una sola.

Verificado con un `World` sintético armado a mano (sin gastar nada): sala
sin moverse (salidas sin confirmar, gate bloqueado mostrado correctamente);
tras cruzar una salida, el edge queda confirmado en ese sentido; un gate
que se abre pero todavía no se cruza sigue "sin confirmar" (ahora con
estado "abierta"); backtracking A→B→A confirma ambos sentidos del edge;
sala de una sola habitación no rompe la función; `_register_world_tools`
agrega la tool en los tres `agent_mode` cuando se pide y hay navegación,
y no la agrega en escenarios de una sola sala aunque se pida. Suite de
conformidad: 78/78.

**Sin correr todavía contra un proveedor real** — a diferencia de las
otras cuatro extensiones, esta no tiene un experimento con números de
Bedrock detrás todavía.

Verificación de las cinco extensiones: ver sección 4 (cada una se probó
con `MockLLMClient`/`World` sintético antes de cualquier corrida paga) y
la suite de conformidad, que se mantuvo en **78/78** a lo largo de todos
los cambios de esta entrega.

## 2. Métricas

**Cuantitativas:**

- **Success rate** (`goal_achieved`, de `check_goal`): mira el estado del
  `World`, no el texto del agente — imposible de falsear con una respuesta
  verborrágica que declara éxito sin haberlo logrado.
- **Eficiencia** (`tool_calls_usados / optimal_calls`, tabla de
  `ENUNCIADO_M3.md` hardcodeada en `metrics.OPTIMAL_CALLS`): distingue un
  agente directo de uno que llega a la meta vagabundeando. 1.0 es óptimo.
- **Costo/latencia**: tokens acumulados (`input_tokens`/`output_tokens`,
  de M2) y tiempo de wall-clock por caso. Bedrock cobra por token, y el
  enunciado lista "coste" y "latencia" como métricas válidas.

**Cualitativa:** rúbrica de 3 dimensiones (`exploracion_dirigida`,
`recuperacion_de_errores`, `uso_de_planificacion`, cada una 1–5 +
justificación) vía LLM-as-judge (`eval.metrics.judge_case`, reusa el propio
`structured_call` del framework). `check_goal` es binario y no distingue
un agente que casi resuelve `office-sequence` de uno que divaga sin rumbo
— la rúbrica da esa señal. Es opt-in (`--judge`) porque duplica el costo de
llamadas al LLM.

**Análisis de errores** (`eval/failure_modes.py`): categoriza cada caso
fallido (nunca los exitosos) en una o más categorías, derivadas solo de
campos observables en `AgentResult`/`AgentStep` — heurísticas, no
certezas:

| Categoría | Señal |
|---|---|
| `excepcion_no_capturada` | `agent.run()` lanzó (viola el contrato M1/M2) |
| `fallo_llm_no_transitorio` | `AgentResult.error` seteado por un fallo real del LLM/proveedor |
| `ciclo_escalado_abortado` | `AgentResult.error` seteado por la escalada de detección de ciclos (sección 1.3.3), no por el proveedor |
| `max_iterations_agotado` | `answer == ""` sin error — agotó el presupuesto de pasos |
| `tool_call_alucinado` | algún `AgentStep.error` contiene "Herramienta desconocida" |
| `argumento_invalido_tool_mundo` | `TypeError` crudo de una tool de `mia_world` por un kwarg mal puesto |
| `accion_repetida_fallida` | el mismo `(tool_name, tool_input)` falla 2+ veces (incluye errores "suaves" que las tools de `mia_world` devuelven como string `"Error: ..."` en vez de lanzar) |
| `desborde_de_contexto` | específico de `extreme-archive`: agotó pasos en el escenario diseñado para no caber en contexto |
| `orden_de_secuencia_violado` | específico de `office-sequence`: `check_goal` reporta violación de orden |
| `perdida_de_mapa_multi_sala` | escenarios multi-sala: tramo de puro `enter:` donde el mismo ciclo corto de salas se repite 3+ veces sin ningún `take`/`open` de por medio (no cuenta backtracking legítimo de una sola vuelta) |
| `se_detuvo_sin_lograr_la_meta` | terminó con texto, sin error, pero el mundo no llegó a la meta |

## 3. Resultados

### 3.1 Evolución hasta la mejor corrida `flat` (sin las 3 extensiones de sección 1.3)

Línea de tiempo condensada de las corridas de calibración de
`max_iterations`/`max_history_messages`/prompt, todas `--scenarios all
--trials 3` salvo donde se indica:

| # | Corrida | Cambio | Éxito global |
|---|---|---|---:|
| 1 | `baseline` | Config default: `system_prompt` genérico, `max_iterations=10`, `max_history_messages=50` | 12-17% |
| 2 | `iterations_100-buggy` | `max_iterations: 10→100`, con bug de ventana deslizante activo (sección 4.1) | 42% |
| 3 | `iterations_100` | Igual, bug corregido | 50% |
| 4-6 | variantes de prompt sin subir iteraciones | prompt largo, `max_history_messages` alto, `max_iterations` en default | 12-17% |
| 7 | `long-prompt-hist-100`* | prompt largo + `max_history_messages=200` + `max_iterations=50` | **83% (n=3)** |
| 8-9 | variantes de historial/iteraciones sobre el mismo prompt | `max_history_messages=100`, `max_iterations` 50→100 | 75% |
| 10 | `long-prompt-estado-t5-h-100-i-100` | prompt con registro de estado explícito, `max_history_messages=100`, `max_iterations=100`, **5 trials** | **78% (n=5)** |

\* nomenclatura de carpeta engañosa: pese al nombre, usó
`max_history_messages=200`, no 100 — el valor real de cada variable
independiente está en el `config` de cada `summary.json`, no en el label.

**Hallazgo dominante de esta fase**: el presupuesto de pasos
(`max_iterations`) domina sobre el prompt. Ninguna corrida con
`max_iterations=10` supera 17%, sin importar el prompt; el salto grande
ocurre siempre que sube a 50+. El prompt largo con registro de estado sí
importa, pero solo *una vez* que hay presupuesto suficiente para actuar
según lo que pide. Un bug real de la ventana deslizante de historial
(mensajes `tool` huérfanos, sección 4.1) se encontró y corrigió en el
camino — confirmado con un fuzz test de 2000 casos y una re-corrida contra
Bedrock.

### 3.2 Estado actual: comparación entre arquitecturas

Con las tres extensiones de framework de la sección 1.3 ya en el código
(detección de ciclos con generalización de período, escalada, y el fix de
falsos positivos de la sección 4.5), estas son las últimas corridas de
cada modo — todas `--scenarios all --trials 3`, mismo prompt
(`prompts/long_prompt_estado.txt`), `max_iterations=100`,
`max_history_messages=100`:

| Escenario | Dificultad | `flat` (§4.5, v7) | `planner` (§4.3, v7) | `subagent` (§4.4, v9) | `adaptive` v1 (§4.6) | `adaptive` v2 (§4.7) |
|---|---|---:|---:|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% | 100% | 100% |
| color-locks | medium | 67% | 33% | 67% | **100%** | 67% |
| library-search | hard | 67% | 0% | 67% | 67% | **100%** |
| extreme-archive | extreme | 100% | 100% | 100% | 33% | 33% |
| apartment-keys | medium | 100% | 100% | 67% | 100% | 33% |
| office-sequence | hard | 67% | 67% | 33% | 67% | **0%** |
| vault-combination | extreme | 67% | 67% | 0% | **0%** | **0%** |
| backtracking-vault | extreme | 33% | 67% | 33% | **0%** | **0%** |
| **TOTAL** | — | **75%** | **67%** | **58%** | **58%** | **42%** |

`adaptive` aparece con dos lecturas a propósito: v2 (poda de la ruta no
elegida) fue pensada como un fix de v1, pero salió peor (42% vs 58%) — la
sección 4.7 explica por qué (el triage sesga fuerte hacia delegar, y la
poda vuelve esa decisión irreversible). Ninguna de las dos es "la"
lectura de `adaptive`; ambas quedan documentadas como parte del mismo
experimento en curso, no como una mejora confirmada. Dos corridas más con
`consultar_mapa` (secciones 4.8 y 4.10) agregan 42% y 54% a la misma
serie — ninguna supera el 58% de la v1 sin podar, y en las cuatro el
factor dominante sigue siendo el mismo (el sesgo del triage hacia
delegar), no el mapa.

`flat` sigue siendo la arquitectura más fuerte en el agregado, pero la
brecha con `subagent` (78 puntos porcentuales al inicio de la saga de la
sección 4.4, con el tope de costo mal calibrado, hasta 20 puntos acá) se
achicó drásticamente una vez que se identificó que la mayor parte de esa
brecha era un bug de framework compartido (no cortar loops), no un
problema de la delegación en sí (ver conclusión de la sección 4.4).
`planner` no mejora el total frente a `flat` sin plan, pero cambia qué
escenarios resuelve — ver sección 4.3. `adaptive` empata con `subagent` en
el total (58%) pero por un motivo distinto y nuevo — ver sección 4.6.

**Nota de varianza**: `backtracking-vault` es el escenario más inestable
de todo el dataset — cuatro lecturas distintas en `flat` a lo largo de
esta entrega (33%/67%/0%/33%) sin que ningún cambio de config lo explique
con confianza más allá de un salto puntual. Ningún número de esta tabla
debería leerse como definitivo sin más trials (sección 5).

### 3.3 Mejor pico histórico

La corrida con más muestra de todo el proyecto (`n=5`, sección 3.1 fila
10) dio **78% de éxito global sobre 40 casos**, con 6 de 8 escenarios al
100% o cerca. La corrida `flat` con `n=3` de la sección 3.2 usa un fix
posterior (detección de ciclos generalizada) y da 75-83% según la
variante exacta — números en el mismo rango, con `n=3` insuficiente para
declarar cuál es estrictamente mejor.

## 4. Experimentos

Se corrieron 5 experimentos que tocan distintas capas del framework y del
prompting — bastante más allá del único experimento de la entrega
original (`max_iterations`).

### 4.1 Presupuesto de pasos (`max_iterations`) y el bug de la ventana deslizante

```
python eval/run.py --scenarios all --trials 3 --label baseline
python eval/run.py --scenarios all --trials 3 --label iterations_100 --max-iterations 100
```

Subir `max_iterations` de 10 a 100 sin tocar nada más casi cuadruplica el
success rate (12%→42% en la primera corrida). Pero la corrida con
`max_iterations=100` destapó un bug real: 12/24 casos morían con

```
ValidationException: The number of toolResult blocks at messages.1.content
exceeds the number of toolUse blocks of previous turn.
```

**Causa** (`_windowed_messages`, `student_framework/agent.py`): la rama que
ancla el último mensaje de usuario cuando la ventana natural lo dejaría
afuera recortaba `keep_after` con un slice de cola que podía cortar *en
medio* de un grupo `assistant(tool_calls=[...])` + sus `tool`, dejando un
mensaje `tool` huérfano en `window[1]` — el chequeo existente solo miraba
`window[0]`. Con conversaciones cortas (`max_iterations=10`) casi no había
oportunidad de activar esa rama; con 100 se volvió común.

**Fix**: `keep_after` descarta sus propios mensajes `tool` huérfanos
iniciales antes de anteponer el mensaje de usuario anclado. Verificado con
un repro exacto y un fuzz test de 2000 combinaciones aleatorias (0
violaciones de la invariante "todo `tool` en la ventana tiene su
`assistant.tool_calls` correspondiente antes en la misma ventana").
Re-confirmado contra Bedrock: `fallo_llm_no_transitorio` pasó de 12/24 a
0/24, y el success rate subió de 42% a 50%.

**Costo de la variante**: no es gratis — duplicó el tiempo total (221.5s→
471.1s en la primera comparación) y en escenarios que agotaban pasos igual
sin lograr la meta, el costo en tokens se disparó sin mejora de éxito.

### 4.2 Estrategia de prompting + presupuesto de historial

Serie de corridas combinando `system_prompt` (genérico → prompt largo con
reglas del mundo → prompt largo + registro de estado explícito) con
`max_history_messages`/`max_iterations` crecientes (tabla completa en
sección 3.1). Hallazgos:

- El prompt largo **solo** importa una vez que hay presupuesto de pasos
  suficiente (50+) — con `max_iterations=10` ningún prompt supera 17%.
- El registro de estado explícito ("mantené una lista de salas
  visitadas/objetos resueltos", "si repetís una acción que ya falló,
  detenete") apunta directo a los dos modos de fallo dominantes una vez que
  el presupuesto dejó de ser el cuello de botella:
  `accion_repetida_fallida` y `perdida_de_mapa_multi_sala`.
- Más presupuesto/historial no es monotónicamente mejor: entre las
  variantes con `max_iterations` 50→100, el éxito global se mantuvo o bajó
  levemente mientras el costo en tokens se disparó (312k vs. 134k de
  entrada, un caso de `library-search` llegó a 676k tokens en un solo
  trial) — evidencia de que el techo pasó a ser ciclos/repetición, no
  presupuesto, motivando el experimento de la sección 4.5.

### 4.3 Planner explícito vs. ReAct puro

Dos corridas separadas por toda la serie de fixes de detección de ciclos
de la sección 4.5 (misma config en ambas: prompt de registro de estado,
`max_history_messages=100`, `max_iterations=100`, `--planner`):

| Escenario | Dificultad | Planner v1 (sin fixes de ciclos) | Planner v7 (con fixes de ciclos) | `flat` v7 (sin planner, mismos fixes) |
|---|---|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% |
| color-locks | medium | 67% | 33% | 67% |
| library-search | hard | 33% | **0%** | 67% |
| extreme-archive | extreme | 100% | 100% | 100% |
| apartment-keys | medium | 100% | 100% | 100% |
| office-sequence | hard | 33% | 67% | 67% |
| vault-combination | extreme | 33% | 67% | 67% |
| backtracking-vault | extreme | 67% | 67% | 33% |
| **TOTAL** | — | **67%** | **67%** | **75%** |

El total agregado quedó empatado entre las dos corridas de planner
(67%→67%), pero la composición se mueve en la misma dirección en ambas: el
planner **ayuda** en escenarios de orden rígido/secuencial
(`backtracking-vault`, `office-sequence`, `vault-combination` — mejoran o
se mantienen altos en ambas corridas) y **perjudica** en el escenario de
descubrimiento puro (`library-search`: "cuál de 8 libros" — empeora en las
dos corridas, y en la segunda cae a 0%). Contra `flat` con el mismo código
de detección de ciclos, el planner queda 8 puntos por debajo (67% vs 75%)
y esa diferencia es casi enteramente `library-search` (0% vs 67%): la
detección de ciclos no compensa ahí porque el agente con planner no queda
atrapado en un patrón detectable — simplemente agota pasos probando libros
sin converger, anclado a un plan generado antes de tener la información
necesaria para hacerlo bien.

**Conclusión**: anteponer un plan fijo de sub-metas ayuda cuando la
dificultad central es el *orden* de las acciones, y perjudica cuando es
*descubrir* información nueva sobre la marcha — confirmado dos veces con
`n=3` cada vez, aunque las dos corridas difieren en el código de detección
de ciclos del framework, así que no son la misma condición exacta y no
deberían promediarse sin más.

### 4.4 Subagentes — delegación de tools

Instoria completa de implementación, incidente de costo, y cuatro rondas de
fixes, cada una verificada con `MockLLMClient` antes de una corrida
paga, y cada una confirmando exactamente el problema puntual que atacaba:

**Incidente inicial — costo desbocado.** Primera corrida real: el caso más
simple del dataset (`study-with-key`, óptimo 3 pasos) tardó 481.9s y agotó
`max_iterations=100` sin responder. De 100 pasos del actor, 51 fueron
`explorar_sala` — el agente nunca reconoció haber logrado el objetivo y
quedó re-verificando el estado indefinidamente; en modo `subagent` cada
re-chequeo dispara una corrida completa del explorador (~333k tokens solo
en el explorador, para un escenario que se resuelve en 3 pasos).

**Fix v1 (tope ciego)**: bajar `max_iterations` del explorador (8→4) +
tope duro `max_calls=6`. Frenó el costo pero **rompió el experimento**:
12% de éxito global — el tope no distingue "re-exploración inútil" de
"el actor genuinamente necesita información nueva", y una vez agotado deja
al actor completamente ciego el resto del `run()`.

**Fix v2 (caché por firma de estado)**: reemplaza el tope por una regla
más honesta — si el mundo no cambió desde la última exploración real, se
devuelve el mismo resumen gratis; en cuanto algo cambia (`take`/`use`/`go`
exitosos), la siguiente exploración vuelve a correr de verdad. Nunca deja
al actor sin poder pedir el estado actual. Resultado: **29%** — mejoró el
tiempo, pero expuso un problema de arquitectura, no de costo: el actor
navega peor entre salas en `subagent` que en `flat`, y la calidad/formato
del resumen del explorador variaba mucho entre invocaciones (a veces en
inglés, con `<thinking>` filtrado, duplicado).

**Fix de formato** (`EXPLORER_SYSTEM_PROMPT` con plantilla fija de 6
líneas, español, sin razonamiento filtrado): **29%** de nuevo en el
agregado, pero por razones distintas — `color-locks`/`apartment-keys`
mejoraron, mientras `study-with-key` (100% en *todas* las corridas
anteriores del proyecto) cayó a 33% por una **alucinación de inventario**:
el explorador reportaba `Inventario: llave dorada` sin que el actor la
hubiera tomado nunca, y el actor confiaba en ese texto.

**Fix de verdad determinística** (`_apply_ground_truth`): las líneas
`Inventario:`/`Cerraduras:` del resumen se recalculan siempre desde
`world` en vez de confiar en el LLM explorador, porque son 100%
derivables. `study-with-key` volvió a 100%, pero el total se mantuvo en
**33%** — `apartment-keys` cayó a 0% por un problema no relacionado
(90 repeticiones seguidas de `use` contra un objeto irrelevante, sin
volver nunca a la sala correcta): el mismo patrón de `accion_repetida_fallida`
que venía apareciendo desde la primera baseline, sin relación con
inventario ni formato.

**Fix de detección de ciclos** (sección 4.5, primera versión, período 1
solo): **58%** — el salto más grande de toda la serie, y el único fix que
atacó el loop del agente en sí en vez del contenido del resumen del
explorador. `color-locks` y `apartment-keys` pasaron a 100% sin ningún
otro cambio.

**Escalada + generalización de período** (sección 4.5): bajó a **54%**, y
la investigación de por qué (en vez de asumirlo como regresión) encontró
un **falso positivo real**: `_is_looping` comparaba solo
`(tool_name, tool_input)`, así que `go(direction="sur")` llamado varias
veces con *resultados distintos* (backtracking legítimo por una cadena
lineal de salas, exactamente el mecanismo que `backtracking-vault` exige)
quedaba bloqueado igual. Corregido comparando también
`(tool_output, error)` — con ese fix más `foco` en `explorar_sala`
(permite pedirle al explorador examinar *un* objeto puntual en vez de
barrer toda la sala, motivado porque `library-search` cayó a 0% sin
relación con ciclos, solo por no poder apuntar a "cuál libro"): **58%**
de nuevo, con `library-search` subiendo específicamente de 0% a 67% y
`ciclo_escalado_abortado` bajando de 8 a 2 casos (confirmando que la
mayoría de esos 8 eran el falso positivo, no ciclos genuinos).

**Conclusión de la serie**: la brecha inicial entre `subagent` y `flat`
(29% vs. 78%) resultó estar dominada por un bug de framework compartido
por ambos modos (no cortar loops repetidos), no por la delegación en sí.
Una vez corregido ese bug común, la brecha real se achicó a algo
respetable (58% vs. 75-83%) — la lectura correcta no es "la arquitectura
de subagentes es inviable", sino que separar "leer el mundo" de "decidir
qué hacer" en dos agentes agrega una capa de indirección (verdad que hay
que verificar, formato que hay que fijar, información que hay que poder
apuntar con `foco`) sobre un modelo que de por sí ya tiene dificultad
sosteniendo un plan multi-paso — y esa capa cuesta, pero no es el cuello
de botella dominante que parecía al principio.

### 4.5 Detección de ciclos en el loop del agente

Motivado por `apartment-keys` cayendo a 0% en la sección 4.4 (90
repeticiones de la misma acción sin variar) — el mismo patrón que
`accion_repetida_fallida` venía señalando post-hoc desde la primera
baseline, y que el prompt largo ya pedía explícitamente evitar sin éxito.
Se atacó desde el framework en vez del prompt (ver sección 1.3.3 para el
diseño). Cuatro iteraciones, cada una verificada con `MockLLMClient` y
confirmada contra Bedrock:

1. **Período 1 solo** (`max_consecutive_repeats=2`): bloquea una acción
   idéntica repetida 3 veces. `subagent`: 33%→**58%** (el salto más grande
   de esa serie). `flat`: sin cambio significativo (67%, dentro de
   varianza) — revisando los casos fallidos de esa corrida, **cero pasos
   bloqueados**, así que el fix no tuvo oportunidad de actuar: el patrón de
   fallo dominante ahí era un ciclo de *período > 1* (re-examinar los mismos
   8 libros de `library-search` en el mismo orden, sin repetir nunca la
   misma llamada dos veces seguidas), fuera del alcance de la detección de
   período 1.
2. **Generalización a período 1-8** (`max_cycle_period=8`): detecta
   bloques de cualquier longitud repetidos. `flat`: 67%→**83%**, el mejor
   número de todo el proyecto con `n=3` — `library-search` llega a 100%,
   confirmando directamente la hipótesis puntual. Límite encontrado:
   `apartment-keys` (33%) mostró un trial con 86 de 100 pasos bloqueados
   *consecutivamente* — el modelo recibía el aviso correctivo y volvía a
   pedir la misma acción bloqueada, sin usar la pista para cambiar de
   estrategia.
3. **Escalada** (`max_blocked_repeats=5`): si el bloqueo se sostiene más de
   5 veces sin ninguna ejecución real en el medio, `run()` corta la
   ejecución en vez de seguir agotando pasos sin chance real. Confirma la
   hipótesis de `apartment-keys`: 33%→**100%**. Pero expuso el falso
   positivo de `go` documentado en la sección 4.4 (`backtracking-vault`
   cayó a 0% en `flat`, aunque revisando los otros dos trials —que
   corrieron los 100 pasos completos sin ninguna escalada y tampoco
   llegaron a la meta— la escalada no fue la causa; es varianza en un
   escenario ya de por sí volátil).
4. **Fix del falso positivo**: comparar `(tool_output, error)` además de
   `(tool_name, tool_input)` en el historial de pasos ya ejecutados, para
   no bloquear una acción cuyo resultado real cambió entre invocaciones
   "idénticas". `flat`: mismo 75% agregado, pero `backtracking-vault`
   (el escenario exacto del hallazgo) mejora 0%→33% y
   `ciclo_escalado_abortado` desaparece del todo (2→0) — la lectura
   correcta no es "no sirvió", es que el resto del movimiento agregado
   (ruido en `color-locks`/`office-sequence`, sin relación con `go`) se
   canceló casi exactamente con la mejora real.

**Conclusión**: de las tres extensiones de framework de esta entrega, la
detección de ciclos fue la de mayor impacto medido — pasó `flat` de 67% a
83% y `subagent` de 33% a 58% con el mismo mecanismo genérico, sin ninguna
lógica específica del mundo de escape-rooms. Su límite más claro es que
bloquear una acción repetida solo ayuda cuando el modelo tiene *otra* idea
disponible; si no la tiene, solo cambia el modo de fallo (de agotar pasos
repitiendo, a terminar antes por escalada), no lo elimina.

### 4.6 La capa adaptativa contra un proveedor real: 58%, y un modo de fallo nuevo — parálisis por exploración redundante

```
python eval/run.py --scenarios all --trials 3 --label adaptive-t3-h100-i100 \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado.txt \
    --agent-mode adaptive --adaptive
```

Bedrock `amazon.nova-lite-v1:0`, 24 casos, 1770.6s total.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 8.3 / 3 | 0.39 | 4.7 | 27127/406 | 8.0 |
| color-locks | medium | 3 | **100%** | 18.0 / 11 | 0.62 | 18.0 | 75475/1133 | 21.7 |
| library-search | hard | 3 | 67% | 20.3 / 7 | 0.37 | 16.5 | 102796/1175 | 26.6 |
| extreme-archive | extreme | 3 | 33% | 51.0 / 4 | 0.11 | 24.0 | 905330/2987 | 96.4 |
| apartment-keys | medium | 3 | 100% | 12.7 / 7 | 0.57 | 12.7 | 49190/716 | 26.0 |
| office-sequence | hard | 3 | 67% | 80.7 / 13 | 0.19 | 24.0 | 587803/4332 | 119.0 |
| vault-combination | extreme | 3 | **0%** | 100.7 / 21 | 0.21 | — | 745869/5431 | 154.6 |
| backtracking-vault | extreme | 3 | **0%** | 62.3 / 18 | 0.80 | — | 675753/4204 | 137.3 |
| **TOTAL** | — | 24 | **58%** | — | — | — | — | — |

Costo oculto del explorador: 70 llamadas, 346.301 tokens de entrada, 20.014
de salida — mucho más bajo que las corridas de `subagent` puro (sección
4.4, 136-232 llamadas), consistente con que acá el explorador es una
opción entre varias, no la única vía de información.

Modos de fallo:

| Categoría | backtracking-vault | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 3 | 2 | 1 | 1 | 3 | 10 |
| `ciclo_escalado_abortado` | 2 | 1 | — | — | — | 3 |
| `desborde_de_contexto` | — | 1 | — | — | — | 1 |
| `max_iterations_agotado` | 1 | 1 | — | 1 | 3 | 6 |
| `perdida_de_mapa_multi_sala` | — | — | — | — | 3 | 3 |

**58% total, el mismo número que `subagent`, pero por un motivo distinto.**
`color-locks` mejora respecto a *todas* las demás arquitecturas (100%, vs.
67% en `flat`/`subagent` y 33% en `planner`) y `apartment-keys` se sostiene
en 100% — en esos dos, tener ambas rutas de exploración disponibles a la
vez no perjudicó. Pero `vault-combination` y `backtracking-vault` —los dos
escenarios `extreme` con la cadena de dependencias más profunda del
dataset— caen a **0%**, el peor resultado de cualquier arquitectura para
esos dos escenarios en toda la reentrega.

**Revisando la transcripción cruda de `backtracking-vault_t2`** (100 pasos,
sin éxito, sin escalada) aparece un patrón que no se había visto en
ninguna corrida anterior — ni en `flat` (solo `look`/`examine`) ni en
`subagent` puro (solo `explorar_sala`, sin alternativa):

```
0.  explorar_sala {}
1.  explorar_sala {"foco": null}
2.  explorar_sala {"foco": null}
3.  explorar_sala {"foco": null}
4.  explorar_sala {"foco": null}
5.  examine {"target": "cofre_antiguo"}
6.  look {}
7.  explorar_sala {"foco": null}
8.  examine {"target": "puerta_principal"}
9.  look {}
10. examine {"target": "cofre_antiguo"}
...
94. examine {"target": "cofre_antiguo"}
95. explorar_sala {"foco": null}
96. examine {"target": "puerta_principal"}
97. explorar_sala {"foco": null}
98. examine {"target": "cofre_antiguo"}
99. explorar_sala {"foco": null}
```

**Los 100 pasos completos son `explorar_sala`/`examine`/`look` — cero
`take`, `use` o `go`.** El agente nunca intentó actuar; se quedó alternando
entre las dos rutas de exploración (la directa y la delegada), re-leyendo
la misma información una y otra vez sin nunca comprometerse a tomar un
objeto, usarlo, o moverse de sala. La detección de ciclos (sección 4.5) no
lo corta porque la secuencia no repite el mismo bloque corto de forma
estricta (alterna targets distintos de `examine`, y `explorar_sala()`
cacheado que en teoría da el mismo resultado se intercala con llamadas que
sí varían) — evade la ventana de período 1-8 sin ser, en la práctica,
ningún progreso real. `case_backtracking-vault_t0` muestra la variante más
extrema: los 9 pasos hasta la escalada son **puro `explorar_sala`**, sin
un solo intento de acción real antes de que la detección de ciclos corte
la ejecución.

**Hipótesis, consistente con la evidencia disponible**: tener *dos* rutas
redundantes para obtener la misma información de la sala (`look`/`examine`
directas y `explorar_sala`, con o sin `foco`) le da al modelo una salida
siempre disponible para "seguir juntando información" en vez de actuar con
lo que ya tiene — un problema de arquitectura, no del contenido de lo que
devuelve cada ruta (ambas reportan datos correctos; `_apply_ground_truth`,
sección 1.3.2, sigue vigente en modo `adaptive`). Ni `flat` (una sola ruta
de exploración) ni `subagent` puro (una sola ruta, sin alternativa directa)
tienen esta salida de escape disponible, así que agotan la exploración
razonable más rápido y se ven forzados a intentar acciones reales antes.
No se confirmó con más casos (`n=3`) — es la lectura más consistente con
la transcripción encontrada, no una certeza estadística.

`vault-combination` (0%, igual que en `subagent` puro, sección 4.4) parece
ser el patrón ya documentado de pérdida de mapa multi-sala
(`perdida_de_mapa_multi_sala` en los 3 trials, oscilación `look`/`go` sin
converger) más que el patrón nuevo de arriba — no hay evidencia de
alternancia `explorar_sala`/`examine` sin actuar en esos casos, el problema
ahí es navegación, no parálisis exploratoria.

**Conclusión de este experimento (v1, sin poda)**: la capa adaptativa, tal
como estaba implementada en esta corrida, no mejora sobre las
arquitecturas fijas — empata con `subagent` (58%) y queda 17 puntos por
debajo de `flat` (75%), con dos escenarios extreme en 0%. El hallazgo de
valor no es "la capa no sirve", es específico y accionable: **registrar
ambas rutas de exploración a la vez (`agent_mode="adaptive"`) puede
introducir una salida de escape que no existe en `flat` ni en `subagent`
puro** — el modelo puede posponer indefinidamente el momento de actuar
porque siempre hay una forma más de "mirar de nuevo".

**Fix aplicado (v2, sección 1.3.4)**: en vez de que el triage solo
recomiende una ruta como texto, ahora **poda** del agente la ruta que no
eligió (elimina la tool de `self._tools`/`self._schemas` apenas decide),
cerrando esa salida de escape en cuanto arranca la conversación.
Verificado con `MockLLMClient` (sección 1.3.4), y confirmado contra
Bedrock — pero el resultado real fue **peor**, no mejor (sección 4.7).

### 4.7 Confirmación del fix de poda contra Bedrock: 42%, peor que la v1 sin podar

```
python eval/run.py --scenarios all --trials 3 --label adaptive-t3-h100-i100-v2 \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado.txt \
    --agent-mode adaptive --adaptive
```

Bedrock `amazon.nova-lite-v1:0`, 24 casos, 763.9s total (mucho más rápido
que la v1, 1770.6s — consistente con lo que se ve abajo: la mayoría de los
trials cortan mucho antes de agotar `max_iterations`).

| Escenario | Dificultad | v1 (§4.6, sin poda) | v2 (con poda) |
|---|---|---:|---:|
| study-with-key | easy | 100% | 100% |
| color-locks | medium | **100%** | 67% |
| library-search | hard | 67% | **100%** |
| extreme-archive | extreme | 33% | 33% |
| apartment-keys | medium | **100%** | 33% |
| office-sequence | hard | 67% | **0%** |
| vault-combination | extreme | 0% | 0% |
| backtracking-vault | extreme | 0% | 0% |
| **TOTAL** | — | **58%** | **42%** |

Modos de fallo — `ciclo_escalado_abortado` sube de 3 (v1) a **11** (v2), y
ahora coincide exactamente con `accion_repetida_fallida` categoría por
categoría (11 y 11): en la v2, cuando algo sale mal, sale mal
*rápido y por la misma razón* en vez de agotar el presupuesto de distintas
formas.

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | — | 3 | 1 | 1 | 3 | 3 | 11 |
| `ciclo_escalado_abortado` | — | 3 | 1 | 1 | 3 | 3 | 11 |
| `fallo_llm_no_transitorio` | — | — | — | 1 | — | — | 1 |
| `se_detuvo_sin_lograr_la_meta` | 2 | — | — | — | — | — | 2 |

**Causa raíz, encontrada revisando `case_office-sequence_t0.json`** (10
pasos, corte por escalada): el triage decidió `delegate_exploration_needed
= True`, así que la poda dejó únicamente `explorar_sala` disponible (más
`take`/`use`/`go`, que siguen siempre registradas). El modelo llama
`explorar_sala()` **sin argumentos, 10 veces seguidas** — como el mundo no
cambió entre llamadas, la caché por firma de estado (sección 1.3.2)
devuelve el resumen idéntico cada vez, así que la 3ª repetición ya
coincide con la definición exacta de ciclo período-1 y la detección la
bloquea; a la 6ª vez bloqueada, escala y corta `run()`. El modelo nunca
intentó `take`/`use`/`go` ni una vez.

**Esto no es un caso aislado — es el patrón dominante.** Clasificando las
24 transcripciones por qué ruta terminó usando cada trial (mirando si
`explorar_sala` aparece entre los `AgentStep`, contra `look`/`examine`):

| Ruta elegida por el triage | Trials | Éxitos |
|---|---:|---:|
| Delegada (`explorar_sala`, poda `look`/`examine`) | 20 | 6 (30%) |
| Directa (`look`/`examine`, poda `explorar_sala`) | 4 | 4 (100%) |

**El triage recomienda delegar en 20 de 24 trials (83%)** — casi siempre,
independientemente de la dificultad real del escenario — y una vez que
recomienda delegar, la poda lo vuelve **irreversible**: si la exploración
delegada no alcanza para resolver el escenario (típicamente porque el
modelo, como ya se documentó en la conclusión de la sección 4.4 para
`subagent` puro, pierde el hilo de la navegación multi-sala cuando no
tiene `look`/`examine` directos), no hay forma de volver atrás dentro de
esa conversación. Los 4 casos con ruta directa son casi todos
`study-with-key` (escenario de una sola sala, donde delegar no tendría
sentido y el triage aparentemente lo nota bien) más un trial de
`apartment-keys` que sale perfecto en 14 pasos.

**Conclusión**: la poda (v2) no falló porque la idea de cerrar la ruta no
elegida esté mal — falló porque **expuso, en vez de resolver, un problema
más grande y ya conocido**: el triage tiene un sesgo fuerte hacia
recomendar delegación (83% de los trials) sin que eso se corresponda con
qué tan bien le va efectivamente a la exploración delegada en escenarios
multi-sala (30% de éxito ahí, contra 100% en los pocos casos que
quedaron con exploración directa). En la v1 (sin poda), ese mismo sesgo
existía pero el modelo podía "escaparse" hacia `look`/`examine` cuando
`explorar_sala` no alcanzaba — ineficiente (la parálisis de la sección
4.6) pero no fatal. La poda cierra esa escapatoria antes de saber si la
decisión del triage era buena, y cuando no lo es (la mayoría de las
veces, en los escenarios más difíciles), el resultado es peor que dejarla
abierta. En otras palabras: **el cuello de botella no era "dos rutas
disponibles a la vez", era que el triage decide mal con qué frecuencia
delegar** — podar solo cambia el costo de esa mala decisión, no la
corrige. Una iteración que atacaría la causa real (no implementada):
hacer la poda reversible — si tras N pasos con la ruta elegida no hubo
ningún `take`/`use`/`go` real, reabrir la otra ruta en vez de mantener el
compromiso inicial para siempre.

### 4.8 `consultar_mapa` contra un proveedor real: casi no se usa sin mención explícita en el prompt

Dos corridas con `--room-graph` (sección 1.3.5), mismo prompt de siempre
(`prompts/long_prompt_estado.txt`, que **no menciona** `consultar_mapa` —
la tool está registrada pero nada en el prompt le dice al modelo cuándo
usarla):

```
python eval/run.py --scenarios all --trials 3 --label flat-t3-h100-i100-roomgraph \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado.txt --room-graph

python eval/run.py --scenarios all --trials 3 --label adaptive-t3-h100-i100-roomgraph \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado.txt \
    --agent-mode adaptive --adaptive --room-graph
```

Bedrock `amazon.nova-lite-v1:0`, 24 casos cada una (1468.9s y 1241.0s).

| Escenario | Dificultad | `flat` v7 (§4.5, sin mapa) | `flat` + mapa (§4.8) | `adaptive` v2 (§4.7, sin mapa) | `adaptive` + mapa (§4.8) |
|---|---|---:|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% | 100% |
| color-locks | medium | 67% | 67% | 67% | **100%** |
| library-search | hard | 67% | 67% | **100%** | 33% |
| extreme-archive | extreme | 100% | 100% | 33% | 67% |
| apartment-keys | medium | 100% | **67%** | 33% | **0%** |
| office-sequence | hard | 67% | 67% | **0%** | 33% |
| vault-combination | extreme | 67% | **33%** | 0% | 0% |
| backtracking-vault | extreme | 33% | 33% | 0% | 0% |
| **TOTAL** | — | **75%** | **67%** | **42%** | **42%** |

**El motivo del resultado no es que el mapa dé información mala — es que
casi no se usó.** Contando invocaciones reales de `consultar_mapa`: **12
llamadas en cada corrida, concentradas en 1 solo caso de las 24**
(`backtracking-vault_t0` en `flat`, `backtracking-vault_t2` en
`adaptive`) — 23 de los 24 casos de cada corrida no la llamaron ni una
vez, incluidos los que más se habrían beneficiado
(`apartment-keys_t0` en `flat`: 65 `go` sin un solo `consultar_mapa`;
`vault-combination_t1`: 62 `go`, cero `consultar_mapa`). El 67%/42% de
estas corridas es, en gran parte, la misma varianza de `n=3` sobre
escenarios ya volátiles (`apartment-keys`, `vault-combination`) que se
viene documentando en toda la reentrega, no un efecto real de la tool —
porque la tool, en la práctica, no participó.

En `adaptive` además se reconfirma exactamente el hallazgo de la sección
4.7 sin relación con el mapa: el triage sigue delegando en 21 de 24 casos
(87%), y varios trials de `apartment-keys`/`backtracking-vault` vuelven a
mostrar el patrón de spam de `explorar_sala` idéntico cortado por
escalada en menos de 20 pasos — `consultar_mapa` sigue registrada y
disponible en esos trials (la poda del triage solo afecta a
`look`/`examine`/`explorar_sala`, nunca a `consultar_mapa`), pero como el
prompt no la menciona, tampoco se usa ahí para salir del atolladero.

**Conclusión**: esta corrida no prueba ni refuta la hipótesis de que un
mapa determinístico ayuda a la navegación — prueba que **una tool no
mencionada en el prompt, sin importar cuán bien diseñada esté, compite
mal por atención contra una lista larga de tools y no se usa**. Ya se
preparó la variante de prompt que menciona `consultar_mapa` explícitamente
(`prompts/long_prompt_estado_mapa.txt`, agrega tres menciones puntuales:
que existe, que conviene llamarla antes de cada `go`, y que sigue haciendo
falta trackear objetos aparte) — la comparación real queda pendiente de
correr con esa variante.

### 4.9 `flat` + mapa con el prompt que lo menciona: 88%, el mejor número del proyecto — pero con una causa que no es la que parece

```
python eval/run.py --scenarios all --trials 3 --label flat-t3-h100-i100-roomgraph-v2 \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado_mapa.txt --room-graph
```

Bedrock `amazon.nova-lite-v1:0`, 24 casos, 1169.5s total.

| Escenario | Dificultad | `flat` v7 (§4.5, sin mapa) | `flat` + mapa, prompt viejo (§4.8) | `flat` + mapa, prompt nuevo (§4.9) |
|---|---|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% |
| color-locks | medium | 67% | 67% | 67% |
| library-search | hard | 67% | 67% | **100%** |
| extreme-archive | extreme | 100% | 100% | 100% |
| apartment-keys | medium | 100% | 67% | 100% |
| office-sequence | hard | 67% | 67% | 67% |
| vault-combination | extreme | 67% | 33% | 67% |
| backtracking-vault | extreme | 33% | 33% | **100%** |
| **TOTAL** | — | **75%** | **67%** | **88%** |

Modos de fallo — el más limpio de toda la reentrega, solo 3 categorías,
ninguna nueva:

| Categoría | color-locks | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 1 | 1 | 3 |
| `max_iterations_agotado` | 1 | 1 | 1 | 3 |
| `perdida_de_mapa_multi_sala` | — | — | 1 | 1 |

**Antes de atribuirle el salto al mapa, hay que mirar si de verdad se
usó** — y acá la evidencia es incómoda. `consultar_mapa` se llamó **32
veces, concentradas en solo 3 de los 24 casos** (`apartment-keys_t0`/`t1`,
1 vez cada uno; `office-sequence_t0`, 30 veces). Más mención en el prompt
que en la sección 4.8 (0 usos), pero lejos de "el modelo adoptó la tool
como herramienta central".

**`backtracking-vault` —el escenario que explica casi todo el salto
(33%→100%)— tiene `consultar_mapa=0` en los 3 trials.** Es el mismo
escenario que ya lleva cuatro lecturas distintas en `flat` a lo largo de
toda esta entrega (33%/67%/0%/33%, ninguna con mapa) — con esta, son
**cinco lecturas** (33/67/0/33/**100**), y la más alta de todas coincide
con la corrida que menos la explica por el mecanismo que se estaba
probando. La lectura más honesta no es "el mapa resolvió
`backtracking-vault`", es que sigue siendo el escenario más volátil del
proyecto y esta vez tocó una tirada muy buena — con `n=3`, no hay forma de
distinguirlo de una mejora real del prompt reescrito (la sección
"Registro de estado" cambió de redacción, no solo agregó menciones del
mapa) sin correr más trials.

**`library-search` sí mejora limpiamente (67%→100%)**, pero tampoco usó
`consultar_mapa` ni una vez — `library-search` no es un escenario
multi-sala (es una sola sala con 8 libros), así que la tool ni siquiera
aplicaría ahí; la mejora es, otra vez, variedad de muestra o efecto del
resto del prompt reescrito, no del mapa.

**El único caso donde se usó de verdad y en volumen
(`office-sequence_t0`, 30 llamadas) terminó fallando** —agotó
`max_iterations` sin responder—, así que tampoco hay ahí evidencia de que
usarla mucho garantice nada.

**Conclusión, con la misma cautela que ya se aplicó varias veces en esta
reentrega**: 88% es el mejor número registrado, pero **no hay evidencia
en las transcripciones de que `consultar_mapa` sea la causa** — se usó en
3 de 24 casos, y el escenario que más aportó a la suba (`backtracking-vault`)
no la usó en absoluto. La hipótesis original (agregar un mapa
determinístico ayuda a la navegación multi-sala) queda **no confirmada,
no refutada**: la tool sigue sin adoptarse de forma consistente ni con
mención explícita en el prompt, así que esta corrida no la pone a prueba
de verdad, aunque el número total sea bueno. Haría falta o bien un prompt
todavía más insistente (o una regla dura del framework que la llame
automáticamente antes de cada `go`, en vez de depender de que el modelo
elija hacerlo), o más trials para separar la varianza real del efecto
puntual — ninguna de las dos se hizo en esta entrega.

### 4.10 `adaptive` + mapa con el prompt que lo menciona: 54%, mejora modesta que tampoco es atribuible al mapa

```
python eval/run.py --scenarios all --trials 3 --label adaptive-t3-h100-i100-roomgraph-v2 \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado_mapa.txt \
    --agent-mode adaptive --adaptive --room-graph
```

Bedrock `amazon.nova-lite-v1:0`, 24 casos, 785.8s total.

| Escenario | Dificultad | `adaptive` v2 (§4.7, sin mapa) | `adaptive` + mapa, prompt viejo (§4.8) | `adaptive` + mapa, prompt nuevo (§4.10) |
|---|---|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% |
| color-locks | medium | 67% | **100%** | 67% |
| library-search | hard | **100%** | 33% | 67% |
| extreme-archive | extreme | 33% | 67% | **100%** |
| apartment-keys | medium | 33% | 0% | 67% |
| office-sequence | hard | **0%** | 33% | 0% |
| vault-combination | extreme | 0% | 0% | 0% |
| backtracking-vault | extreme | 0% | 0% | 33% |
| **TOTAL** | — | **42%** | **42%** | **54%** |

Modos de fallo — `ciclo_escalado_abortado` sigue alto (9, en línea con las
otras dos corridas con poda: 11 y 9):

| Categoría | apartment-keys | backtracking-vault | color-locks | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 2 | 1 | 1 | 3 | 3 | 11 |
| `ciclo_escalado_abortado` | 1 | 2 | — | 1 | 3 | 2 | 9 |
| `max_iterations_agotado` | — | — | — | — | — | 1 | 1 |
| `perdida_de_mapa_multi_sala` | — | — | — | — | — | 1 | 1 |

**54% es, de las tres corridas con poda (4.7/4.8/4.10), la mejor** —
pero sigue 4 puntos por debajo de la v1 original sin podar (58%, sección
4.6) y 34 puntos por debajo del mejor `flat` (88%, sección 4.9). El
patrón de fondo, otra vez, no cambia: el triage sigue delegando en 17 de
24 trials (71% — apenas menos que el 83-87% de las corridas anteriores,
dentro de lo que podría ser ruido), la ruta delegada sigue rindiendo
mucho peor que la directa (6/17 éxitos, 35%, contra 7/7, 100%), y
`consultar_mapa` se usó **17 veces en solo 2 de los 24 casos** —
prácticamente la misma tasa de adopción que en `flat` (sección 4.9, 3/24)
pese a que el prompt es idéntico y sí la menciona explícitamente.

`office-sequence_t0` (47 pasos, falla) usó `consultar_mapa` 12 veces
combinado con `explorar_sala` — el mismo caso que en la sección 4.8 había
usado la tool en volumen (30 veces) y también fallara: la evidencia
disponible en dos corridas separadas apunta en la misma dirección, usar
la tool mucho no correlaciona con resolver el escenario.

**Conclusión**: la mejora de 42%→54% es consistente con las mismas dos
explicaciones que la sección 4.9 ya identificó para `flat` (reescritura
general del prompt + varianza de `n=3`), no con que el mapa haya
resuelto el problema estructural documentado en la sección 4.7 — el
sesgo del triage hacia delegar sigue ahí, casi sin cambios, y sigue
siendo el factor dominante que separa a `adaptive` de `flat`/`planner`.
`consultar_mapa` queda con el mismo diagnóstico que en `flat`: una tool
bien diseñada que, sin una regla dura que fuerce su uso (en vez de
depender de que el modelo la elija), no se adopta lo suficiente como
para poner a prueba si efectivamente ayuda.

## 5. Limitaciones y qué construirían a continuación

- **Varianza a `n=3`**: la mayoría de las corridas de esta entrega usan 3
  trials por escenario para poder iterar rápido sobre el framework;
  `backtracking-vault` en particular lleva **cinco** lecturas distintas en
  `flat` (33%/67%/0%/33%/**100%**, la última en la sección 4.9) sin que
  ningún cambio de config lo explique con confianza — la lectura de 100%
  coincide, además, con una corrida donde la tool que se estaba probando
  (`consultar_mapa`) no se usó ni una vez en ese escenario, así que ni
  siquiera tiene una explicación causal candidata. Antes de afirmar
  cualquier conclusión puntual con seguridad (en especial la del planner,
  sección 4.3, la comparación `subagent` vs. `flat`, sección 3.2, y el
  88% de la sección 4.9) hace falta una corrida con más trials (5, como la
  mejor corrida histórica) sobre los escenarios más volátiles en vez de
  repetir los 8 completos.
- **`vault-combination`** no se resolvió en ninguna variante de
  `subagent` (0% en las últimas dos corridas) — no hay un fix propuesto
  todavía, más allá de que es, junto con `backtracking-vault`, el
  escenario con la cadena de dependencias más profunda del dataset.
- **La rúbrica LLM-as-judge no es determinística**; se reporta como
  referencia cualitativa, no como métrica dura.
- **Las categorías de `failure_modes.py` son heurísticas** basadas en
  texto de error y conteos de acciones, no en inspección semántica del
  `World` — pueden tener falsos positivos/negativos, y de hecho varias
  secciones de este informe documentan casos donde hubo que revisar la
  transcripción cruda para no leer mal un número agregado.
- **`build_agent` no filtra las tools de M1** cuando corre contra el mundo
  simulado — ruido conocido en el tool-list, no resuelto porque el
  enunciado no pide especializar `build_agent` para M3.
- **El harness de timeout por caso (sección 1.2) tiene sus propios límites**:
  usa `SIGALRM`, así que solo funciona en el hilo principal y en sistemas
  POSIX (no Windows), y es de un solo disparo por caso — si el corte ocurre
  durante la ejecución de una tool en vez de una llamada al LLM (`_execute_tool`
  también atrapa cualquier excepción y la convierte en un error de paso en
  vez de dejarla propagar), el `run()` seguiría consumiendo `max_iterations`
  después sin un segundo aviso. No se activó ese camino en la práctica
  (las tools del mundo son síncronas y rápidas), pero es una asimetría
  conocida del diseño, no probada exhaustivamente.
- **La capa adaptativa (secciones 1.3.4/4.6/4.7) no mejora sobre las
  arquitecturas fijas en ninguna de sus dos versiones** — v1 (sin poda)
  dio 58%, v2 (con poda de la ruta no elegida) dio **42%, peor todavía**.
  El fix de la v2 atacó el síntoma correcto (parálisis alternando rutas)
  pero expuso un problema más grande y ya conocido: el triage recomienda
  delegar la exploración en el 83% de los trials (20/24), casi sin
  correlación con la dificultad real del escenario, y esa exploración
  delegada solo tiene 30% de éxito cuando se usa — contra 100% en los
  pocos casos que quedaron con exploración directa. Podar vuelve esa
  decisión sesgada **irreversible** dentro de la conversación, así que el
  costo de una mala decisión del triage (frecuente) ya no tiene forma de
  corregirse a mitad de camino. La causa raíz no es la disponibilidad de
  tools, es que el triage decide mal con qué frecuencia conviene delegar.
  Iteración futura razonable (no implementada): poda **reversible** — si
  tras N pasos con la ruta elegida no hubo ningún `take`/`use`/`go` real,
  reabrir la otra ruta en vez de mantener el compromiso inicial para
  siempre. Con el presupuesto de esta entrega, se documenta como un
  experimento concluido con resultado negativo en ambas variantes, no como
  algo a seguir iterando sin una razón de peso para esperar que la
  próxima iteración sí funcione.
