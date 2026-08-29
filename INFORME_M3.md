# Informe — Milestone 3

> Estado: baseline y experimento 3 (`max_iterations`) corridos contra Bedrock
> (`amazon.nova-lite-v1:0`). El experimento 3 destapó un bug real de la
> ventana deslizante de M2 (ventana con `tool` huérfano — ver sección 4),
> que se corrigió y **re-confirmó contra Bedrock**: el modo de fallo del bug
> (`fallo_llm_no_transitorio`) pasó de 12/24 casos a 0/24, y el success rate
> subió de 12% (baseline) a 50% (con el fix). **Pendiente**: experimentos 1
> (ventana de historial) y 2 (prompting).

## 1. Aproximación

El agente que resuelve los escenarios es exactamente el de M1+M2
(`student_framework/agent.py`), sin ninguna especialización para el mundo
simulado: mismo `run`, misma ventana deslizante de historial, mismos
reintentos ante fallos transitorios. Lo único que cambia por caso es qué
tools están registradas — las del mundo (`mia_world.tools.make_world_tools`)
se agregan sobre un agente recién construido con `build_agent(config)`,
igual que ya lo hacía `mia_world/cli.py::_cmd_run` para una corrida manual.

Nota: `build_agent` registra siempre las tres tools de M1 (`simple_calc`,
`leer_archivo`, `optimizar_portfolio_markowitz`) además de las del mundo —
no se filtran para los escenarios de M3. Es el mismo comportamiento que ya
tenía la CLI de `mia_world`; no lo cambiamos porque el enunciado no pide
tocar `build_agent` de forma especial, pero es una fuente de ruido en el
tool-list que el LLM ve (herramientas irrelevantes para una sala de escape).

Lo que sí es trabajo nuevo de M3 es la infraestructura de evaluación,
construida en `eval/`:

- **`eval/runner.py`**: `run_case`/`run_suite`. Por cada escenario y cada
  trial, copia (`copy.deepcopy`) el `World` inicial del escenario —
  necesario porque las tools mutan el `World` en sitio, así que reusar la
  misma instancia entre trials contaminaría el punto de partida de los
  siguientes—, construye un agente fresco, corre `agent.run(user_message)` y
  captura: `AgentResult` completo, tiempo de wall-clock, resultado de
  `check_goal` y el `event_log` del mundo. Envuelve la llamada a `agent.run`
  en `try/except` para que una excepción inesperada de un caso no aborte el
  resto de la suite (el contrato de M1/M2 dice que `run` nunca debería
  lanzar; si lo hace, se registra como su propio modo de fallo en vez de
  tirar abajo la corrida). Además, antes de correr, envuelve todas las
  tools ya registradas en el agente (`_instrument_goal_progress`) para
  reevaluar `check_goal` después de cada invocación — así cada caso guarda
  `goal_achieved_at_step`, el número de paso exacto en el que se cumplió la
  meta (distinto de "pasos totales usados", que puede incluir acciones
  posteriores). Verificado de forma determinística con un `MockLLMClient`
  scripteado antes de usarlo en una corrida paga.
- **`eval/run.py`**: CLI reproducible (`python eval/run.py`). Resuelve
  escenarios por id, dificultad o `all` (una dificultad expande a *todos*
  sus escenarios — a diferencia de `mia_world.cli._resolve_scenario`, que
  toma solo el primero, acá hace falta la suite completa), acepta overrides
  de config (`--max-history-messages`, `--max-iterations`,
  `--system-prompt`, o un JSON arbitrario con `--config`) para poder
  reusarse en baseline y en cada experimento sin tocar código, y un flag
  `--judge` opcional para correr además la rúbrica cualitativa (cuesta el
  doble de llamadas al LLM, por eso es opt-in). Deja un JSON por caso más
  `summary.json`/`summary.md` en `eval/results/<label>/`, sin pasos
  manuales entre la corrida y el informe.
- **`eval/metrics.py`** y **`eval/failure_modes.py`**: ver secciones 2 y 3.

## 2. Métricas

**Cuantitativas:**

- **Success rate** (`goal_achieved`, de `check_goal`): mira el estado del
  `World`, no el texto del agente — es la métrica que pide el enunciado
  precisamente porque es imposible de falsear con una respuesta verborrágica
  que declara éxito sin haberlo logrado.
- **Eficiencia** (`tool_calls_usados / optimal_calls`, tabla de
  `ENUNCIADO_M3.md` hardcodeada en `metrics.OPTIMAL_CALLS` porque no vive en
  el JSON del escenario): distingue un agente que resuelve el escenario de
  forma directa de uno que llega a la meta después de vagabundear. 1.0 es
  óptimo; valores bajos indican exploración redundante.
- **Costo/latencia**: tokens acumulados (`input_tokens`/`output_tokens` de
  `AgentResult`, ya implementados en M2) y tiempo de wall-clock por caso.
  Justificado porque Bedrock cobra por token y el enunciado lista
  explícitamente "coste" y "latencia" como métricas válidas.

**Cualitativa:** rúbrica de 3 dimensiones (`exploracion_dirigida`,
`recuperacion_de_errores`, `uso_de_planificacion`, cada una 1–5 +
justificación) vía LLM-as-judge, implementada reusando el propio
`structured_call` del framework (`eval.metrics.judge_case`, agente separado
sin tools sobre la transcripción de `steps`). Justificación: `check_goal` es
binario y no distingue un agente que casi resuelve `office-sequence` (llega
al orden correcto pero se equivoca en el último paso) de uno que divaga sin
rumbo — la rúbrica da esa señal donde el booleano no alcanza. Es opt-in
(`--judge`) porque duplica el costo de llamadas al LLM.

## 3. Análisis de errores

`eval/failure_modes.py` categoriza cada caso fallido (nunca los exitosos) en
una o más de estas categorías, derivadas únicamente de campos observables en
`AgentResult`/`AgentStep` — son heurísticas, no certezas absolutas:

| Categoría | Señal |
|---|---|
| `excepcion_no_capturada` | `agent.run()` lanzó (viola el contrato de M1/M2) |
| `fallo_llm_no_transitorio` | `AgentResult.error` seteado — un fallo del LLM agotó los reintentos dentro de `run()` |
| `max_iterations_agotado` | `answer == ""` sin error — la única forma en que nuestro `run()` devuelve eso es agotando el presupuesto de pasos |
| `tool_call_alucinado` | algún `AgentStep.error` contiene "Herramienta desconocida" |
| `argumento_invalido_tool_mundo` | `TypeError` crudo de una tool de `mia_world` (fijas, sin mensajes accionables como las nuestras) por un kwarg mal puesto — encontrado en el smoke test (ver más abajo) |
| `accion_repetida_fallida` | el mismo `(tool_name, tool_input)` falla 2+ veces — el agente no aprende del error |
| `desborde_de_contexto` | específico de `extreme-archive`: agotó pasos en el escenario diseñado para no caber en el contexto |
| `orden_de_secuencia_violado` | específico de `office-sequence` (goal `sequence`): `check_goal` reporta violación de orden |
| `perdida_de_mapa_multi_sala` | escenarios multi-sala: navega (`go`) más del doble de veces que direcciones distintas pidió — aproximado, no distingue backtracking legítimo (p. ej. `backtracking-vault`, que lo requiere por diseño) |
| `se_detuvo_sin_lograr_la_meta` | terminó con texto, sin error, pero el mundo no llegó a la meta — se rindió o creyó haber terminado sin lograrlo |

Durante el smoke test (`study-with-key`, Ollama local `llama3.1:latest`, no
representativo del proveedor final) apareció un ejemplo real de
`argumento_invalido_tool_mundo`: el LLM invocó `take(target="llave")` en vez
de `take(item="llave")`; como la tool del mundo no valida kwargs con un
mensaje accionable, salió como `TypeError: take_impl() got an unexpected
keyword argument 'target'` — capturado sin romper la corrida por
`_execute_tool`, pero sin ayudar al modelo a corregirse. Esa fue justamente
la motivación para agregar esta categoría específica en vez de dejarlo caer
en "sin categorizar".

## 4. Experimentos

Tres experimentos planeados (diseño en `plan_m3.md`); **experimento 3 ya
ejecutado**, 1 y 2 pendientes:

1. **Ventana de historial** (`max_history_messages` chico, p. ej. 8, vs.
   default 50) — foco en los multi-sala (`apartment-keys`,
   `office-sequence`, `vault-combination`, `backtracking-vault`); el
   enunciado señala que `apartment-keys` "pone a prueba la memoria de
   estado del M2". *Pendiente.*
2. **Estrategia de prompting** (`system_prompt` genérico vs. uno que pide
   descomponer el objetivo en sub-metas antes de actuar) — foco en
   `office-sequence` (goal `sequence`), que el enunciado plantea
   directamente como "planner explícito vs. ReAct puro". *Pendiente.*
3. **Presupuesto de pasos** (`max_iterations` default vs. ajustado) —
   **ejecutado**, ver abajo.

### Experimento 3: presupuesto de pasos (`max_iterations`)

#### Escenario base con promp inútil y max_iteration por default (10)
```
python eval/run.py --scenarios all --trials 3 --label baseline 
```


| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.7 / 3 | 0.53 | 5.7 | 11386/346 | 5.5 |
| color-locks | medium | 3 | 0% | 10.0 / 11 | 1.10 | — | 20797/734 | 9.7 |
| library-search | hard | 3 | 0% | 10.0 / 7 | 0.70 | — | 25437/683 | 9.4 |
| extreme-archive | extreme | 3 | 33% | 15.0 / 4 | 0.32 | 25.0 | 39204/1039 | 11.5 |
| apartment-keys | medium | 3 | 33% | 12.3 / 7 | 0.60 | 17.0 | 20213/555 | 8.5 |
| office-sequence | hard | 3 | 0% | 11.0 / 13 | 1.19 | — | 20637/553 | 8.5 |
| vault-combination | extreme | 3 | 0% | 14.7 / 21 | 1.60 | — | 21992/760 | 10.0 |
| backtracking-vault | extreme | 3 | 0% | 10.0 / 18 | 1.80 | — | 20682/576 | 8.6 |
| **TOTAL** | — | 24 | **21%** | — | — | — | — | — |


#### Escenario base con promp inútil y max_iteration por default (10) con prompt 


```
python eval/run.py --scenarios all --trials 3 --label baseline --system-prompt "Sos un agente que resuelve puzzles tipo escape-room explorando una sala con herramientas (look/examine/take/use/go). Antes de actuar, descomponé el objetivo en una lista corta de sub-metas ordenadas y perseguilas una por una en ese orden; no actúes de forma puramente reactiva paso a paso."
```


```
python eval/run.py --scenarios apartment-keys office-sequence vault-combination backtracking-vault \
    --trials 3 --label exp1-history-8 --max-iterations 100 --max-history-messages 8

```



```
python eval/run.py --scenarios office-sequence \
    --trials 3 --label exp2-prompt-planner --max-iterations 100 \
    --system-prompt "Sos un agente que resuelve puzzles tipo escape-room explorando una sala con herramientas (look/examine/take/use/go). Antes de actuar, descomponé el objetivo en una lista corta de sub-metas ordenadas y perseguilas una por una en ese orden; no actúes de forma puramente reactiva paso a paso."

```

```
python eval/run.py --scenarios all --trials 3 --label iterations_100
--max-iterations 100
```
mismo dataset y `--trials` que la baseline, Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 471.1s total (vs. 221.5s de la baseline
— el doble de tiempo, ver nota de costo abajo).

**Nota**: esta primera corrida (resultados en
`eval/results/iterations_100-buggy/`) tenía activo el bug de la ventana
deslizante descripto más abajo — 12 de los 24 casos murieron con un error
de Bedrock a mitad de camino, así que estos números subestiman lo que el
agente puede lograr con 100 pasos. Quedan igual como registro de lo que
mostró la corrida que originó el hallazgo del bug; la sección "Confirmación
post-fix" más abajo trae la corrida limpia con el fix aplicado, que es la
que hay que leer como resultado final del experimento.

| Escenario | Success (`max_iter=10`) | Success (`max_iter=100`) | Δ | Calls media (100) / óptimo | Paso medio de meta (100) |
|---|---:|---:|---:|---:|---:|
| study-with-key | 100% | 100% | = | 5.3 / 3 | 5.3 |
| color-locks | 0% | 0% | = | 26.0 / 11 | — |
| library-search | 0% | 33% | **+33** | 17.0 / 7 | 19.0 |
| extreme-archive | 0% | 67% | **+67** | 24.3 / 4 | 24.0 |
| apartment-keys | 0% | 100% | **+100** | 12.3 / 7 | 12.3 |
| office-sequence | 0% | 0% | = | 20.7 / 13 | — |
| vault-combination | 0% | 33% | **+33** | 27.7 / 21 | 28.0 |
| backtracking-vault | 0% | 0% | = | 25.0 / 18 | — |
| **TOTAL** | **12%** | **42%** | **+30** | — | — |

**Confirma la hipótesis de la sección 5**: subir `max_iterations` de 10 a
100 sin tocar nada más del agente casi cuadruplica el success rate global
(12% → 42%). Tres lecturas puntuales:

- **`apartment-keys` pasa de 0% a 100%**: el escenario que el enunciado
  señala como prueba de memoria multi-sala se resuelve perfecto en cuanto
  hay presupuesto de pasos — sugiere que el problema de M2 ahí no era la
  memoria (`max_history_messages=50` de default nunca se acercó a
  recortar nada en corridas de ~12 pasos), era pura y simplemente el techo
  de `max_iterations=10`.
- **`extreme-archive` pasa de 0% a 67% — hay que corregir la lectura de la
  baseline**: en la sección 5 categoricé sus fallos como
  `desborde_de_contexto` asumiendo que el escenario (diseñado para no
  caber en ~16K tokens) rompía disciplina de tool-calling. Con más
  presupuesto de pasos se resuelve la mayoría de las veces — así que el
  fallo en la baseline era mayormente el mismo cuello de botella de pasos
  que todo lo demás, no un problema de contexto per se. Eso sí, el costo
  es brutal: 222.313 tokens de entrada promedio (vs. 39.364 en la
  baseline, ~5.6x) — el escenario sigue siendo caro incluso cuando se
  resuelve.
- **`color-locks`, `office-sequence` y `backtracking-vault` siguen en 0%**
  aun con 100 pasos disponibles: ahí el presupuesto de pasos no era (o no
  era solo) el problema — son los candidatos naturales para los
  experimentos 1 (memoria) y 2 (prompting/planificación) pendientes.

**Costo de la variante**: más presupuesto de pasos no es gratis. Duplicó
el tiempo total (221.5s → 471.1s) y en escenarios donde terminó gastando
todos los pasos igual sin lograr la meta (`color-locks`: 26.0 calls media,
más del doble del óptimo 11) el costo en tokens también se disparó sin
ninguna mejora en success rate. Es un trade-off, no una mejora
estrictamente gratuita.

### Bug encontrado por el experimento: mensajes `tool` huérfanos en la ventana deslizante

Los modos de fallo de esta corrida muestran algo que no estaba en la
baseline: `fallo_llm_no_transitorio` en 12 de los 24 casos (0 en la
baseline). Los 12 tienen el **mismo error exacto** de Bedrock:

```
ValidationException: The number of toolResult blocks at messages.1.content
exceeds the number of toolUse blocks of previous turn.
```

Esto es un bug real en `_windowed_messages` (`student_framework/agent.py`),
no un problema del proveedor ni del modelo. La rama que ancla el último
mensaje de usuario cuando la ventana "natural" lo dejaría afuera
(necesaria justamente para conversaciones largas — exactamente lo que
`max_iterations=100` produce) recorta `keep_after` con un slice de cola:

```python
after_user = history[last_user_idx + 1 :]
keep_after = after_user[-(cap - 1) :] if cap > 1 else []
window = [history[last_user_idx]] + keep_after
```

Si ese slice corta *en medio* de un grupo `assistant(tool_calls=[...])` +
sus mensajes `tool` de respuesta, `keep_after` puede arrancar con un
mensaje `tool` huérfano — su `tool_calls` correspondiente quedó afuera de
la ventana. El chequeo que evita justo eso (`while window[0].get("role")
== "tool"`) solo mira `window[0]`, que acá es el mensaje de usuario
anclado (rol `"user"`), **no** `window[1]`, donde puede estar el huérfano.
Bedrock lo rechaza porque ese turno tiene un `toolResult` sin `toolUse`
que lo respalde.

Reproducido de forma determinística, sin gastar nada, manipulando
`agent._history` directamente:

```python
agent = MyAgent(llm_client=MockLLMClient([]), max_history_messages=4)
agent._history = [
    {"role": "user", "content": "user0"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", ...}, {"id": "c2", ...}]},
    {"role": "tool", "tool_call_id": "c1", "content": "r1"},
    {"role": "tool", "tool_call_id": "c2", "content": "r2"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c3", ...}]},
    {"role": "tool", "tool_call_id": "c3", "content": "r3"},
]
agent._last_user_index = 0
agent._windowed_messages()
# -> [user0, tool(c2) <- huérfano, assistant(c3), tool(c3)]
```

`tool(c2)` queda en `window[1]` sin su `assistant(tool_calls=[c1,c2])`
correspondiente — exactamente el patrón que Bedrock rechazó en producción.
Con conversaciones cortas (baseline, `max_iterations=10`) casi no había
oportunidad de que la ventana necesitara la rama de anclaje con un corte a
mitad de grupo; con `max_iterations=100` se volvió común, por eso apareció
recién acá. **Corregido** (ver `student_framework/agent.py`): `keep_after`
ahora descarta sus propios mensajes `tool` huérfanos iniciales antes de
anteponer el mensaje de usuario anclado, no solo se revisa `window[0]`.

Verificado con dos capas, ninguna contra Bedrock: (1) el repro exacto de
arriba ahora da `[user0, assistant(c3), tool(c3)]`, sin huérfano; (2) un
fuzz test de 2000 combinaciones aleatorias de `max_history_messages` (1–8)
y cantidad/tamaño de grupos `assistant(tool_calls)+tool` (0–6 grupos, 1–3
calls cada uno), chequeando la invariante "todo mensaje `tool` en la
ventana tiene su `assistant.tool_calls` correspondiente en algún punto
anterior de esa misma ventana" — **0 violaciones**.

### Confirmación post-fix contra Bedrock

Re-corrida idéntica (`--scenarios all --trials 3 --label iterations_100
--max-iterations 100`) con el fix ya aplicado. Resultados en
`eval/results/iterations_100/` (la corrida con bug quedó preservada en
`eval/results/iterations_100-buggy/` como evidencia).

| Escenario | Success (buggy) | Success (fix) | Calls media (fix) / óptimo | Paso medio de meta (fix) |
|---|---:|---:|---:|---:|
| study-with-key | 100% | 100% | 4.7 / 3 | 4.7 |
| color-locks | 0% | 33% | 43.7 / 11 | 26.0 |
| library-search | 33% | 67% | 46.0 / 7 | 18.5 |
| extreme-archive | 67% | 33% | 9.3 / 4 | 23.0 |
| apartment-keys | 100% | 67% | 40.7 / 7 | 11.0 |
| office-sequence | 0% | 33% | 46.7 / 13 | 19.0 |
| vault-combination | 33% | 33% | 95.3 / 21 | 29.0 |
| backtracking-vault | 0% | 33% | 78.0 / 18 | 25.0 |
| **TOTAL** | **42%** | **50%** | — | — |

Modos de fallo (post-fix):

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 2 | 1 | — | 1 | 1 | 1 | 7 |
| `max_iterations_agotado` | 1 | 2 | 1 | — | 1 | 1 | 2 | 8 |
| `perdida_de_mapa_multi_sala` | 1 | 1 | — | — | — | — | 2 | 4 |
| `se_detuvo_sin_lograr_la_meta` | — | — | 1 | 2 | — | 1 | — | 4 |

**El fix está confirmado en producción, no solo en el repro local**:
`fallo_llm_no_transitorio` (el modo de fallo causado por el bug) aparecía
en 12/24 casos en la corrida con bug y **no aparece ni una sola vez** en
esta tabla. Eso solo, más allá del número de success rate, es la evidencia
que buscábamos.

Con el bug ya no interrumpiendo corridas a mitad de camino, el success
rate total subió de 42% a 50% — pero conviene leer los cambios por
escenario con cautela, no como una mejora limpia y uniforme:

- **office-sequence resuelto por primera vez** (0% → 33%, y con la
  secuencia en el orden correcto): la corrida con bug nunca le dio la
  chance real de llegar tan lejos. Sigue siendo el escenario más difícil
  de sostener (2/3 trials fallan igual, ahora por `accion_repetida_fallida`
  y `se_detuvo_sin_lograr_la_meta`, no por el bug) — buen candidato para el
  experimento 2 (prompting/planificación) pendiente.
- **`extreme-archive` bajó de 67% a 33%**: con el bug corregido, las
  corridas duran más y exploran más — pero eso no es estrictamente mejor
  para este escenario en particular; con la variancia de solo 3 trials por
  celda, no se puede distinguir todavía si es ruido del LLM (no
  determinístico) o un efecto real de que conversaciones más largas
  compiten peor en este escenario puntual. No alcanza para una conclusión
  firme con esta muestra.
- **`apartment-keys` bajó de 100% a 67%**: mismo caveat de tamaño de
  muestra (n=3) — no hay evidencia de que el fix en sí perjudique este
  escenario, es más consistente con variancia entre corridas separadas del
  LLM.
- **Costo de arreglar el bug**: antes, un caso que chocaba con la
  excepción de Bedrock terminaba ahí, gastando menos tokens/tiempo (por
  las razones equivocadas). Con el fix, los casos corren su presupuesto
  completo con más frecuencia: el tiempo total subió de 471.1s a 1224.9s
  (2.6x) y escenarios como `vault-combination` pasaron de ~21.7k a ~293k
  tokens de entrada promedio. Corregir el bug fue estrictamente necesario
  para que el experimento midiera lo que dice medir, pero también
  encareció bastante la corrida — un costo real a tener en cuenta antes de
  correr los experimentos 1 y 2 con `max_iterations` alto.

## 5. Resultados

Baseline: `python eval/run.py --scenarios all --trials 3 --label baseline`,
config default (`max_iterations=10`, `max_history_messages=50`), Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 221.5s total. Corrida dos veces (la
segunda ya con tracking de `goal_achieved_at_step` agregado, ver sección
"Herramienta de evaluación" más abajo) — el patrón se sostiene idéntico
entre ambas corridas, así que no es un fluke de una tirada particular.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.0 / 3 | 0.62 | 5.0 | 9423/285 | 4.9 |
| color-locks | medium | 3 | 0% | 13.0 / 11 | 0.93 | — | 22045/766 | 10.4 |
| library-search | hard | 3 | 0% | 10.0 / 7 | 0.70 | — | 26115/724 | 9.9 |
| extreme-archive | extreme | 3 | 0% | 10.0 / 4 | 0.40 | — | 39364/1115 | 12.9 |
| apartment-keys | medium | 3 | 0% | 10.0 / 7 | 0.70 | — | 20160/537 | 8.7 |
| office-sequence | hard | 3 | 0% | 10.0 / 13 | 1.30 | — | 20513/549 | 8.4 |
| vault-combination | extreme | 3 | 0% | 10.3 / 21 | 2.04 | — | 21464/584 | 9.4 |
| backtracking-vault | extreme | 3 | 0% | 10.0 / 18 | 1.80 | — | 20643/587 | 9.0 |
| **TOTAL** | — | 24 | **12%** | — | — | — | — | — |

`study-with-key` es, por ahora, el único escenario con éxitos — su columna
"paso medio de meta" (5.0) coincide exactamente con "calls media" (5.0):
el agente no hace ninguna acción de más después de abrir la puerta, se
detiene apenas cumple el objetivo. El resto muestra "—" porque
`goal_achieved_at_step` solo tiene sentido sobre trials exitosos.

Modos de fallo:

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | — | 1 | — | — | — | — | — | 1 |
| `desborde_de_contexto` | — | — | — | 3 | — | — | — | 3 |
| `max_iterations_agotado` | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 21 |
| `perdida_de_mapa_multi_sala` | — | 1 | — | — | — | — | — | 1 |

**Corrección aplicada al categorizador** (no requirió re-correr nada contra
Bedrock, solo reprocesar los JSON ya guardados): las tools de `mia_world`
señalan varios fallos devolviendo un string `"Error: ..."` como valor de
retorno *normal* en vez de lanzar una excepción — p. ej. `go` contra una
salida bloqueada por una puerta gated. Eso dejaba `AgentStep.error` en
`None`, así que `accion_repetida_fallida` (que originalmente solo miraba
ese campo) no detectaba estos casos. El caso que lo evidenció fue
`backtracking-vault trial=2`: 4 llamadas a `go(direction="norte")`
seguidas — las primeras 2 rebotan contra una puerta blindada bloqueada, la
4ª por fin entra a la sala siguiente — que mi heurística de navegación
etiquetaba como "perdió el mapa" cuando en realidad es "insistió con una
salida bloqueada hasta destrabarla", un patrón bien distinto. Ahora
`eval/failure_modes._step_failed` también cuenta como fallo un
`tool_output` que empieza con `"Error:"`, no solo `AgentStep.error`.

**Hallazgo principal: el cuello de botella no es (mayormente) competencia del
modelo, es el presupuesto de pasos.** `max_iterations=10` es el default
heredado de M1/M2 (elegido ahí para que los tests de conformidad con mocks
corran rápido) — nunca fue calibrado contra el `optimal` real de estos
escenarios, que va de 3 (`study-with-key`) a 21 (`vault-combination`).
`max_iterations_agotado` aparece en 21/24 casos (87.5%). Inspeccionando los
casos crudos se ven dos patrones distintos detrás de esa misma categoría:

- **Corte limpio por presupuesto de rondas**: `office-sequence` y
  `backtracking-vault` terminan con exactamente 10 `AgentStep` (una tool por
  ronda de LLM) — el agente avanzaba de forma serial y razonable hacia la
  meta (navegar, examinar, tomar la llave correcta) pero necesitaba 13–18
  pasos y el loop corta a los 10 sin importar qué tan bien encaminado
  estuviera.
- **Ineficiencia real que agrava el corte**: `color-locks` ejecutó 24
  `AgentStep` (el modelo pidió varios `tool_calls` por respuesta) en esas
  mismas 10 rondas de LLM — más del doble del óptimo (11) — y aun así no
  llegó a la meta. Ahí el problema no es solo el presupuesto: hay
  exploración redundante real.

`study-with-key` (único éxito, 100%) es también el único escenario cuyo
óptimo (3) cabe cómodamente dentro de 10 rondas incluso con margen para
algún error — consistente con la hipótesis de que el techo de pasos, no la
dificultad intrínseca del puzzle, explica la mayor parte del 88% de fallos.

**Esto reordena la prioridad de los experimentos** (sección 4): correr el
experimento de ventana de historial o de prompting *bajo el mismo
`max_iterations=10`* arriesga medir "¿cuántos pasos le quedaban antes de
chocar con el techo?" en vez de la pregunta real de cada experimento. Antes
de esos dos, conviene correr el experimento 3 (presupuesto de pasos) para
establecer un `max_iterations` donde el agente pueda efectivamente terminar
la mayoría de los escenarios, y recién ahí medir el efecto de historia y
prompting sobre una base que no esté saturada por el corte de rondas.

## 6. Limitaciones y próximos pasos

- La rúbrica LLM-as-judge no es determinística; se reporta como referencia
  cualitativa, no como métrica dura.
- Las categorías de `failure_modes.py` son heurísticas basadas en texto de
  error y conteos de acciones, no en una inspección semántica del `World` —
  en particular `perdida_de_mapa_multi_sala` puede tener falsos positivos en
  escenarios que requieren backtracking legítimo por diseño.
- `build_agent` no filtra las tools de M1 (calculadora, lector de archivos,
  portfolio) cuando corre contra el mundo simulado; queda como ruido
  potencial en el tool-list que ve el LLM. No se resolvió porque el
  enunciado no pide especializar `build_agent` para M3.
- El bug de la ventana deslizante (sección 4) solo se detectó porque
  `max_iterations=100` generó conversaciones lo bastante largas como para
  necesitar la rama de anclaje de `_windowed_messages` — con `n=3` trials
  por escenario tampoco hay garantía de que no queden otros bugs de borde
  sin activar. El fuzz test de 2000 casos cubre la invariante puntual del
  bug encontrado, no todo el espacio de comportamiento del agente.
- Próximo paso inmediato: correr los experimentos 1 (ventana de historial)
  y 2 (prompting/planificación) — ahora sobre una base sin el bug de la
  ventana, así que el efecto medido va a ser el de la variable del
  experimento, no una mezcla con crashes de Bedrock. Dado el salto de costo
  que trajo el fix (sección 4), conviene decidir con el usuario cuántos
  escenarios/trials entran en cada uno antes de correrlos.
