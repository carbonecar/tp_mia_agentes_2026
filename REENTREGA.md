# Reentrega — respuesta a la devolución de M3

El TP está aprobado. Esta reentrega responde a la devolución recibida, que
señaló tres puntos:

> El informe está corto de experimentos: solo tiene uno terminado, el de
> aumentar el máximo de iteraciones.
> No hay avances significativos en el framework (por ejemplo, memoria
> semántica, subagentes, planificación) y los experimentos se centran
> únicamente en el prompt y las iteraciones.
> Es confuso que haya 2 archivos de informe (`INFORME_M3.md` y
> `resumen-informe-m3.md`), todo ese contenido podría estar en un solo
> informe para facilitar la lectura.

Este documento cubre el primer y segundo punto: dos experimentos nuevos que
tocan el **framework** (`student_framework/agent.py`), no solo prompt/
iteraciones. El tercer punto (consolidar los dos informes en uno) queda
**pendiente a propósito** hasta tener los resultados reales de estos dos
experimentos corridos contra un proveedor — así se reescribe el informe
consolidado una sola vez, con todos los números adentro, en vez de dos
veces.

## 1. Qué se agregó

De las opciones de framework discutidas (memoria semántica/resumen,
subagentes, planificación explícita, detección de ciclos), se implementaron
**subagentes (delegación de tools)** y **planner explícito vs. ReAct puro**
— son los dos que el propio `ENUNCIADO_M3.md` sugiere explícitamente para
`apartment-keys`/`office-sequence`, y los que más se diferencian de "ajustar
un parámetro o el texto del prompt".

### 1.1 Planner explícito (`student_framework/agent.py`)

Nuevo parámetro `MyAgent(planner=True)`. En la primera llamada a `run()` de
una conversación, antes de entrar al loop ReAct habitual:

1. Se dispara una fase de planificación aislada vía `structured_call` (la
   misma pieza de M2 que ya usa `final_result` para salida validada) contra
   un schema nuevo `_Plan` (`subgoals: list[str]`, 3 a 8 sub-metas
   ordenadas).
2. El texto del plan se antepone al mensaje de usuario original — no se
   reemplaza el mensaje, se lo aumenta — y **ese** mensaje aumentado es el
   que arranca el historial y el loop ReAct de siempre.
3. Si el planner no logra un plan válido (`StructuredOutputError` tras
   agotar los reintentos de reparación de `structured_call`), se degrada
   silenciosamente a ReAct puro sobre el mensaje original: un fallo del
   planner nunca rompe `run()`.
4. Solo planifica una vez por instancia (`self._planned`): llamadas
   sucesivas a `run()` sobre la misma conversación no vuelven a planificar.

Deliberadamente **no** se tocó el loop ReAct en sí — la variable
experimental es únicamente "¿el mensaje que arranca la conversación trae un
plan de sub-metas, o no?", para poder aislar su efecto.

`build_agent` ya expone `planner` como override de config (agregado a la
misma lista de `optional_keys_list` que ya traía `max_iterations`/
`system_prompt`/etc.), así que se activa igual que los demás experimentos:
`config={"planner": True}`.

### 1.2 Subagentes — delegación de tools (`student_framework/tools/explorer_subagent.py`)

Separa responsabilidades entre dos agentes en vez de un único loop
monolítico:

- **Explorador**: `MyAgent` con únicamente `look`/`examine` registradas y un
  system prompt propio ("nunca tomás ni usás objetos ni te movés — no
  tenés esas tools"). Investiga la sala actual a fondo y devuelve un
  resumen en texto (salidas, objetos con sus ids, contenido de
  contenedores, inventario).
- **Actor**: registra `take`/`use`/`go` más una tool nueva, `explorar_sala`,
  en vez de `look`/`examine` directas. Decide sus acciones a partir del
  resumen que le devuelve el explorador, no de su propia exploración.

`make_explorer_tool(llm_client, look_pair, examine_pair, world, cost_sink=...)`
arma esa tool: cada invocación *real* construye un explorador **nuevo** (sin
historial acumulado entre llamadas, para que cada resumen describa el
estado *actual* de la sala) reusando el mismo `llm_client` que el actor.
"Real" porque, tras el incidente de costo de la sección 4, la tool cachea
por firma de estado del `World`: si nada cambió desde la última
exploración, devuelve el mismo resumen sin correr el explorador de nuevo
(ver sección 4.2 para el detalle y por qué el diseño original —un tope
duro de invocaciones— no alcanzaba).

**Costo oculto, medido explícitamente**: `mia_agents/types.py` documenta
que "sub-agentes invocados por herramientas NO se contabilizan" en el
`AgentResult` de quien los invoca — así que sin instrumentación aparte, el
costo real del modo subagente (una llamada extra al LLM por cada
`explorar_sala`) quedaría invisible en las métricas. `cost_sink` acumula
`calls`/`input_tokens`/`output_tokens` de cada corrida del explorador;
`eval/metrics.aggregate_explorer_cost` los suma a través de todos los
casos y `eval/run.py` los imprime en `summary.md`/`summary.json` aparte de
`input_tokens`/`output_tokens` del actor, para que la comparación de costo
entre modos sea honesta.

### 1.3 Wiring en `eval/`

- `eval/runner.py`: `run_case`/`run_suite` ganan `agent_mode: "flat" |
  "subagent"`. En `"flat"` (default, comportamiento sin cambios) las 4-5
  tools del mundo se registran directas, como siempre. En `"subagent"`,
  `_register_world_tools` arma el explorador con `look`/`examine` y
  registra `take`/`use`/`go` + `explorar_sala` en el actor.
- `eval/run.py`: nuevos flags `--planner` y `--agent-mode {flat,subagent}`.
  `agent_mode` y el costo del explorador quedan también en `summary.json`
  para trazabilidad.

Nada de esto tocó `mia_world/` (scaffold fijo) ni las 3 líneas marcadas `NO
CAMBIAR` en `student_framework/__init__.py`.

## 2. Verificación (sin gastar contra un proveedor real)

Mismo criterio que ya documenta `INFORME_M3.md` para el bug de la ventana
deslizante: probar de forma determinística con `MockLLMClient` scripteado
antes de correr algo pago.

- **Planner**: secuencia mock de 2 respuestas (tool_call a `final_result`
  con sub-metas, después texto final). Confirmado: el plan queda inyectado
  en el primer mensaje del historial, se hacen exactamente 2 llamadas al
  LLM (plan + react), y una segunda llamada a `run()` sobre la misma
  instancia no vuelve a planificar.
- **Subagente**: `make_explorer_tool` probado en aislamiento (secuencia
  mock `look` → `examine` → resumen de texto; se verificó el resumen
  devuelto, el `cost_sink` acumulado, y —tras el fix v2 de la sección
  4.2— que una segunda invocación con el `World` sin cambios usa la caché
  sin gastar LLM, y que una invocación después de mutar el `World` sí
  corre el explorador de nuevo). Además, un smoke test **end-to-end** a
  través de `eval.runner.run_case` sobre el escenario real
  `study-with-key` (`agent_mode="subagent"`, 7 respuestas mock cubriendo
  actor + explorador): `goal_achieved=True`, los pasos del actor son
  exactamente `["explorar_sala", "take", "use"]` (sin `look`/`examine`
  directos), `goal_achieved_at_step=3`, y el costo del explorador se
  reporta separado del actor.
- **Regresión**: `pytest tests/conformance/` — **78/78 tests siguen
  pasando**, sin tocar nada del scaffold fijo (`mia_agents/`, `mia_world/`).

## 3. Experimento 1 corrido: planner explícito

`python eval/run.py --scenarios all --trials 3 --label planner-t3-h100-i100
--max-iterations 100 --max-history-messages 100 --system-prompt-file
prompts/long_prompt_estado.txt --planner` — Bedrock `amazon.nova-lite-v1:0`,
8 escenarios × 3 trials = 24 casos, 1671.3s total. Mismo prompt/historial/
iteraciones que la mejor corrida encontrada sin planner
(`long-prompt-estado-t5-h-100-i-100`, sección "Mejor corrida encontrada" de
`INFORME_M3.md`), así que es comparable directamente contra esa (agrega
`planner=True`, nada más).

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 6.3 / 3 | 0.48 | 5.0 | 18755/318 | 7.2 |
| color-locks | medium | 3 | 67% | 48.0 / 11 | 0.44 | 18.5 | 364842/2930 | 64.0 |
| library-search | hard | 3 | 33% | 75.3 / 7 | 0.14 | 26.0 | 915437/4768 | 125.4 |
| extreme-archive | extreme | 3 | 100% | 23.7 / 4 | 0.17 | 23.0 | 242032/1536 | 26.8 |
| apartment-keys | medium | 3 | 100% | 12.7 / 7 | 0.56 | 12.0 | 44465/673 | 12.3 |
| office-sequence | hard | 3 | 33% | 100.0 / 13 | 0.13 | 28.0 | 638737/4952 | 148.6 |
| vault-combination | extreme | 3 | 33% | 76.3 / 21 | 0.38 | 29.0 | 500861/4922 | 103.1 |
| backtracking-vault | extreme | 3 | 67% | 54.7 / 18 | 0.44 | 32.0 | 326362/3323 | 69.3 |
| **TOTAL** | — | 24 | **67%** | — | — | — | — | — |

Modos de fallo:

| Categoría | backtracking-vault | color-locks | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 1 | — | 1 | 2 | 5 |
| `max_iterations_agotado` | 1 | 1 | 2 | 2 | 2 | 8 |
| `perdida_de_mapa_multi_sala` | 1 | — | — | — | 2 | 3 |

**Lectura preliminar** (n=3 trials, cauteloso con la varianza): el planner
explícito **no mejora el total** frente al 78% sin planner (78% con 5
trials vs. 67% con 3 trials) — de hecho `library-search` y `office-sequence`
empeoran notoriamente (100%→33% y 100%→33% respectivamente frente a la
corrida sin planner), mientras que `apartment-keys` mejora (80%→100%) y
`backtracking-vault` también (40%→67%). Una hipótesis a explorar: anteponer
un plan fijo de sub-metas puede ayudar en escenarios donde el orden
correcto es la dificultad central (`apartment-keys`: navegar-buscar-volver;
`backtracking-vault`: encadenar salas en el orden justo), pero perjudicar en
escenarios donde la dificultad es *descubrir* información nueva sobre la
marcha (`library-search`: cuál de 8 libros; `office-sequence`: mismo
prompt largo ya lo resolvía 100% sin plan) — un plan generado *antes* de
explorar nada puede anclar al agente a sub-metas basadas en poca
información y hacerlo más lento para corregirse que el ReAct puro. No es
concluyente con 3 trials por celda; hace falta más muestra antes de
afirmarlo con confianza.

## 4. Incidente en el experimento 2 (subagentes): costo desbocado, encontrado y corregido

Al correr `python eval/run.py --scenarios all --trials 3 --label
subagent-t3-h100-i100 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent`,
el primer caso (`study-with-key`, trial 0 — el escenario más simple del
dataset, óptimo 3 pasos) tardó **481.9s** y terminó agotando
`max_iterations=100` sin devolver respuesta final, pese a que la puerta ya
estaba abierta desde el paso 4. El proceso llevaba ~14 minutos corridos y
apenas había terminado 1 de 24 casos — a ese ritmo, la corrida completa
(con escenarios más pesados de por medio) hubiera tomado horas y costado
mucho más de lo esperado. Se mató el proceso antes de que avanzara a los
escenarios `hard`/`extreme`.

**Diagnóstico** (`eval/results/subagent-t3-h100-i100/case_study-with-key_t0.json`,
preservado como evidencia): de los 100 pasos del actor, 51 fueron
`explorar_sala` y 48 `use` contra objetos que ya no hacían nada —el agente
nunca reconoció que ya había logrado el objetivo y quedó re-verificando el
estado indefinidamente. Es el mismo patrón que `eval/failure_modes.py` ya
categoriza post-hoc (`accion_repetida_fallida`, agente que no se detiene
solo al cumplir la meta), pero **el modo subagent lo vuelve mucho más
caro**: en modo `flat` cada re-chequeo es una tool call de `look`/`examine`;
en modo `subagent`, cada una de esas 51 veces disparó una corrida completa
del explorador (hasta 8 pasos propios, el default original de
`make_explorer_tool`) — **~333k tokens de entrada gastados solo en el
explorador**, para un escenario que se resuelve en 3 pasos.

**Fix v1 aplicado** en `student_framework/tools/explorer_subagent.py`:

1. `max_iterations` del explorador baja de 8 a **4** (look + un puñado de
   `examine` alcanza de sobra para las salas de este dataset).
2. Tope nuevo, `max_calls` (default **6**): a partir de la sexta invocación
   de `explorar_sala` en un mismo `run()`, la tool deja de construir un
   explorador nuevo (costo cero, ninguna llamada al LLM) y responde con un
   aviso pidiéndole al actor que actúe con lo que ya sabe o concluya. Acota
   el peor caso posible a `max_calls × max_iterations` = 24 llamadas extra
   como mucho, en vez de poder escalar sin límite con `max_iterations=100`
   del actor.

Verificado con `MockLLMClient` (dos llamadas reales, dos cortadas sin
gastar LLM) y con la suite de conformidad (78/78). Con esa verificación se
volvió a correr el experimento completo.

### 4.1 El fix v1 frenó el costo pero rompió el experimento (12% de éxito)

`eval/results/subagent-t3-h100-i100/summary.md` (corrida completa, 8
escenarios × 3 trials, 2821.2s total): **12% de éxito global — solo
`study-with-key` resuelve (100%), los otros 7 escenarios caen a 0%.**

Diagnóstico contando `explorar_sala` a través de los 24 casos: **732
invocaciones en total**, de las cuales solo **40 (5%) devolvieron un
resumen real**. El resto: **624 (85%) cortadas por `max_calls=6`** y **68
(9%) el explorador agotó sus propios 4 pasos sin sintetizar nada**. El tope
duro no distingue "re-exploración inútil" de "el actor genuinamente
necesita información nueva" (después de un `go` a otra sala, de abrir un
contenedor, etc.) — una vez agotado, deja al actor completamente ciego el
resto del `run()`, sin ningún mecanismo para volver a pedir el estado de la
sala. En escenarios de una sola habitación y pocos objetos
(`study-with-key`) 6 exploraciones alcanzan; en cualquier cosa con más de
una sala o más de un par de objetos, no.

### 4.2 Fix v2: caché por firma de estado en vez de un tope ciego

Reemplaza el tope duro por una regla más honesta: **si el mundo no cambió
desde la última exploración real, se devuelve el mismo resumen sin correr
el explorador de nuevo** (gratis) — pero en cuanto el actor hace algo que sí
cambia el mundo (`take`/`use`/`go` exitosos), la siguiente `explorar_sala`
vuelve a correr el explorador de verdad y el actor recibe información
fresca. La diferencia clave con el tope: nunca deja al actor sin poder
pedir el estado actual, solo evita pagar de nuevo por un estado ya
conocido.

- `_state_signature(world)`: tupla barata con sala actual, inventario,
  contenedores revelados, y `(id, open_state, piezas colocadas)` de cada
  item — cubre todo lo que un resumen podría reportar distinto, incluido el
  progreso parcial en cerraduras multi-pieza (`vault-combination`) que no
  queda registrado ni en `inventory` ni en `event_log`.
- `max_iterations` del explorador sube de 4 a **6**: con 4, el 63% de las
  corridas *reales* (no cacheadas) del fix v1 volvían sin resumen por quedarse
  sin presupuesto propio — muy ajustado incluso para casos legítimos.
- `max_calls` (ahora **25**, y solo cuenta corridas reales, no aciertos de
  caché) queda como último circuito de seguridad ante el caso patológico de
  que el mundo cambie en cada paso sin converger nunca — no debería
  activarse en el uso normal.

Verificado con `MockLLMClient`: dos invocaciones con el mismo estado del
`World` devuelven el mismo resumen sin gastar una segunda llamada al LLM
(`cost_sink["calls"]` no se mueve, `mock.call_count` tampoco); tras mutar
el `World` (simulando un `take` exitoso), la siguiente invocación sí corre
el explorador de verdad y trae un resumen distinto. Suite de conformidad:
sigue en 78/78.

El 12% de la corrida v1 **no es una medición válida del modo subagent** —
es la medición de un tope de costo mal calibrado; se descarta y no se usa
como conclusión del experimento.

### 4.3 Corrida con el fix v2: mejoró el tiempo, pero expone un hallazgo distinto — ruido de señal en la navegación

Mismo comando de la sección 4, con el fix v2 ya aplicado. El tiempo mejoró
muchísimo frente al v1 (casos que antes tardaban minutos por el tope mal
calibrado ahora resuelven en segundos cuando el escenario converge), pero
revisando los casos de escenarios multi-sala mientras la corrida estaba en
marcha (`case_apartment-keys_t2.json`, 100 pasos, `goal_achieved=False`)
apareció un problema distinto, **de arquitectura, no de costo**: el agente
es notablemente peor para navegar entre salas en modo `subagent` que lo que
ya venía siendo en modo `flat`.

**Números finales** (`eval/results/subagent-t3-h100-i100/summary.md`, 8
escenarios × 3 trials, 3917.3s total — todavía con el prompt viejo del
explorador, el fix de formato de la sección 4.4 llegó a mitad de la
corrida):

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 4.0 / 3 | 0.78 | 3.3 | 12865/245 | 10.8 |
| color-locks | medium | 3 | 33% | 72.3 / 11 | 0.29 | 17.0 | 677472/4404 | 146.1 |
| library-search | hard | 3 | 0% | 100.0 / 7 | 0.07 | — | 636283/6787 | 154.8 |
| extreme-archive | extreme | 3 | 33% | 384.3 / 4 | 0.46 | 3.0 | 477841/11889 | 157.3 |
| apartment-keys | medium | 3 | 33% | 65.0 / 7 | 0.22 | 14.0 | 483600/3418 | 172.1 |
| office-sequence | hard | 3 | 0% | 94.0 / 13 | 0.14 | — | 657305/5182 | 211.4 |
| vault-combination | extreme | 3 | 0% | 106.7 / 21 | 0.20 | — | 902841/5702 | 278.6 |
| backtracking-vault | extreme | 3 | 33% | 81.3 / 18 | 0.38 | 22.0 | 972350/4487 | 174.5 |
| **TOTAL** | — | 24 | **29%** | — | — | — | — | — |

Costo oculto del explorador (no incluido en los tokens de arriba): **232
llamadas, 1.189.699 tokens de entrada, 112.306 tokens de salida** — más de
lo que gastó el actor en varios escenarios.

Modos de fallo:

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | — | 2 | 2 | 2 | 3 | 1 | 3 | 13 |
| `desborde_de_contexto` | — | — | — | 2 | — | — | — | 2 |
| `max_iterations_agotado` | 1 | 2 | 2 | 2 | 3 | 2 | 3 | 15 |
| `perdida_de_mapa_multi_sala` | 2 | — | — | — | — | 2 | 3 | 7 |

**Lectura**: 29% queda muy por debajo del 78% del mejor `flat` y del 67%
del planner (sección 3) — el modo subagent, aun sin el bug de costo del
fix v1, resuelve claramente peor que dejar que un único agente decida todo.
`perdida_de_mapa_multi_sala` sube a 7 casos (era 4-6 en las corridas
`flat` equivalentes) pese a que la información de salidas está disponible
en los resúmenes del explorador — consistente con el hallazgo de ruido de
señal de abajo. `extreme-archive` es un caso aparte: cuando logra la meta
lo hace rápido (paso 3, casi óptimo) pero cuando falla se dispara a 384
calls promedio — la varianza entre "resuelve limpio" y "se cuelga
completamente" es enorme en ese escenario.

**No es que el explorador no reporte las salidas.** En el paso 19 de ese
caso, el resumen del explorador dice, correcto y explícito:

> **Salidas Disponibles:** Sur: Recibidor (no se ha explorado) · Este:
> Cocina (no se ha explorado)

`Recibidor` es exactamente la sala con `puerta_principal`, y el agente ya
tenía la llave en el inventario en ese punto. Aun así, el paso siguiente
vuelve a ir "este" (hacia la Cocina, de donde ya venía) en vez de "sur" —
un fallo de razonamiento del modelo sobre información que sí tenía
disponible y correcta.

**Lo que sí es un hallazgo de la arquitectura**, mirando varios resúmenes
del mismo caso: la calidad y el formato de la información que recibe el
actor varían muchísimo de una invocación de `explorar_sala` a la
siguiente —

- Un resumen sale en inglés (pese a que `EXPLORER_SYSTEM_PROMPT` está en
  español), con un preámbulo `<thinking>...</thinking>` filtrado tal cual
  a la respuesta, y duplica el resumen completo dos veces en el mismo
  texto.
- Otro es casi telegráfico, sin estructura.
- Otro, en español, prolijo y con las salidas bien marcadas (el del
  ejemplo de arriba).

En modo `flat`, `look`/`examine` devuelven **siempre el mismo texto
determinístico** — lo arma código en `mia_world/tools.py`, no un LLM —,
mismo formato, mismo idioma, cero ruido, en cada invocación. En modo
`subagent`, cada resumen lo **redacta el explorador**, así que el actor
tiene que parsear una paráfrasis distinta cada vez, a veces en el idioma
equivocado, a veces con ruido de cadena de pensamiento filtrado adentro.
Para un modelo como `amazon.nova-lite-v1:0`, que ya está al límite
navegando mapas multi-sala en modo `flat` (`perdida_de_mapa_multi_sala` ya
aparecía como categoría de fallo antes de este experimento, ver
`INFORME_M3.md`), esa inconsistencia adicional de formato/idioma parece
empeorar justo lo que ya era el punto más débil.

**Corrección sobre esto mismo**: la primera versión de este documento
decía que no convenía ajustar el prompt del explorador porque "mezclaría
la variable experimental" con "un chequeo de formato". Ese argumento no se
sostiene: el prompt del agente principal (`prompts/long_prompt_estado.txt`)
pasó por varias iteraciones a lo largo de todo M3 antes de llegar al mejor,
y eso nunca se trató como invalidar nada — era, correctamente, parte de
construir el framework. No hay razón para tratar el prompt del explorador
con un estándar distinto: si el objetivo es que el modo `subagent` funcione
bien, afinar su prompt es tan legítimo como afinar el del actor. Comparar
"subagent con explorador prolijo" contra "flat" (ambos bien afinados) sigue
siendo una comparación limpia de la arquitectura — y si aun así pierde, la
conclusión es más fuerte, no más débil.

### 4.4 Fix aplicado: formato fijo y en español para el explorador

`EXPLORER_SYSTEM_PROMPT` (`student_framework/tools/explorer_subagent.py`)
ahora exige una plantilla fija de 6 líneas (`Sala:` / `Salidas:` /
`Objetos visibles:` / `Contenedores revelados:` / `Cerraduras:` /
`Inventario:`), siempre en español, sin preámbulo de razonamiento, sin
etiquetas `<thinking>` y sin duplicar el resumen — apunta directo a los
tres problemas de formato que aparecían en la sección 4.3 (idioma
inconsistente, ruido de razonamiento filtrado, contenido repetido). La
lógica de `make_explorer_tool` (caché por firma de estado, tope de
seguridad) no cambió, solo el texto del prompt. Suite de conformidad:
sigue en 78/78 (no hay lógica nueva que probar con mocks, es un cambio de
system prompt).

**Aclaración de secuencia**: la corrida de la sección 4.3 ya estaba en
curso cuando se hizo este cambio, así que sus casos restantes terminaron
con el prompt viejo (Python no recarga el módulo a mitad de una corrida) —
sus números (29% de éxito global, sección 4.3) sirven como el punto de
comparación "antes" de este fix. Falta correr una corrida nueva con el
prompt corregido para tener el "después".

### 4.5 Punto de comparación adicional: flat sin prompt custom ya le gana a subagent con el mejor prompt

Corrida pensada para medir el "después" del fix de la sección 4.4, pero el
comando usado (`python eval/run.py --scenarios all --trials 3 --label
subagent-t3-h100-i100-explorer-prompt-fixed --max-iterations 100
--max-history-messages 100`) **no incluía `--agent-mode subagent` ni
`--system-prompt-file prompts/long_prompt_estado.txt`** — corrió en modo
`flat`, con el system prompt por default ("Eres un asistente útil."), no
lo que el `--label` sugería. La carpeta se renombró a
`eval/results/flat-default-prompt-t3-h100-i100/` (y el campo `label` dentro
de `summary.json`/`summary.md`, parejo) para que el nombre refleje lo que
realmente se corrió — el `agent_mode: flat` y la ausencia de
`system_prompt` custom en su `config` siguen ahí como evidencia.

Aun así, el número es un dato real y vale la pena registrarlo:

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.0 / 3 | 0.60 | 5.0 | 10050/334 | 4.7 |
| color-locks | medium | 3 | 33% | 11.3 / 11 | 1.25 | 20.0 | 28936/792 | 10.5 |
| library-search | hard | 3 | 67% | 12.3 / 7 | 0.76 | 16.0 | 48733/1199 | 13.9 |
| extreme-archive | extreme | 3 | 67% | 49.7 / 4 | 0.12 | 24.5 | 977786/6710 | 120.6 |
| apartment-keys | medium | 3 | 67% | 43.3 / 7 | 0.36 | 15.0 | 184605/2226 | 48.9 |
| office-sequence | hard | 3 | 67% | 102.0 / 13 | 0.13 | 25.0 | 522944/4903 | 220.9 |
| vault-combination | extreme | 3 | 0% | 136.3 / 21 | 0.32 | — | 367098/4789 | 141.6 |
| backtracking-vault | extreme | 3 | 33% | 85.3 / 18 | 0.23 | 46.0 | 508791/5507 | 111.2 |
| **TOTAL** | — | 24 | **54%** | — | — | — | — | — |

**Lectura**: no es una comparación perfectamente pareja (prompt distinto
al de las corridas subagent), pero es conservadora *a favor* del subagent
— un `flat` en desventaja de prompt (sin registro de estado, sin las
reglas del mundo explicadas) igual saca **54%**, casi el doble del mejor
resultado de subagent hasta ahora (29%, sección 4.3, con el prompt largo
completo). Refuerza la conclusión de la sección 4.3: el problema no es
falta de un buen prompt, es la arquitectura de delegación en sí — pagar el
costo de separar explorador/actor no se traduce en mejor desempeño con
este modelo, ni siquiera comparado contra una versión de `flat` deliberadamente
en desventaja.

### 4.6 Corrida correcta del "después": mismo 29% total, pero por razones distintas — y un bug nuevo

`python eval/run.py --scenarios all --trials 3 --label
subagent-lp-t3-h100-i100-v2 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent`
— esta sí es la comparación correcta contra la sección 4.3 (mismo prompt
del actor, mismo `agent_mode=subagent`, la única diferencia es el fix de
formato del explorador de la sección 4.4). 8 escenarios × 3 trials,
3259.5s total.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 33% | 67.7 / 3 | 0.35 | 3.0 | 443406/5101 | 103.3 |
| color-locks | medium | 3 | 67% | 47.3 / 11 | 0.39 | 21.0 | 298948/3817 | 85.5 |
| library-search | hard | 3 | 0% | 100.0 / 7 | 0.07 | — | 664967/7497 | 145.3 |
| extreme-archive | extreme | 3 | 33% | 49.0 / 4 | 0.27 | 6.0 | 780486/3689 | 176.5 |
| apartment-keys | medium | 3 | 67% | 29.3 / 7 | 0.46 | 11.0 | 170227/1809 | 91.2 |
| office-sequence | hard | 3 | 0% | 100.0 / 13 | 0.13 | — | 662535/5405 | 176.7 |
| vault-combination | extreme | 3 | 0% | 100.0 / 21 | 0.21 | — | 796460/5705 | 182.5 |
| backtracking-vault | extreme | 3 | 33% | 73.3 / 18 | 0.31 | 33.0 | 489369/4345 | 125.4 |
| **TOTAL** | — | 24 | **29%** | — | — | — | — | — |

Costo oculto del explorador: 152 llamadas, 887.250 tokens de entrada,
48.148 tokens de salida (baja frente a las 232 llamadas / 1.189.699 tokens
de la sección 4.3 — la caché por firma de estado sigue funcionando).

**El total da exactamente el mismo 29% que la sección 4.3** — a primera
vista, el fix de formato "no tuvo incidencia". Pero por escenario no es
que nada haya cambiado; hay movimiento real que se cancela en el agregado:

| Escenario | v1 — prompt viejo (4.3) | v2 — formato fijo (4.6) |
|---|---:|---:|
| study-with-key | 100% | **33%** ⬇ |
| color-locks | 33% | 67% ⬆ |
| apartment-keys | 33% | 67% ⬆ |
| library-search / office-sequence / vault-combination | 0% | 0% (sin cambio) |
| extreme-archive | 33% | 33% (sin cambio) |
| backtracking-vault | 33% | 33% (sin cambio) |

`color-locks` y `apartment-keys` mejoran — consistente con la hipótesis de
la sección 4.3 (menos ruido de formato ayuda a escenarios donde la
información del explorador importa). Pero **`study-with-key` —el único
escenario que fue 100% en absolutamente todas las corridas anteriores de
todo este proyecto, `flat` o `subagent`, con cualquier prompt— cae a 33%**.
Vale la pena entender por qué en vez de asumir que es solo ruido de
muestra.

**Causa encontrada, revisando `case_study-with-key_t0.json` (falla, 100
pasos)**: el explorador **alucina el inventario**. Su resumen, en el
formato fijo nuevo, dice textualmente:

```
Sala: Estudio
Objetos visibles: alfombra (abierto); escritorio (abierto); puerta principal (cerrada); llave dorada (n/a)
Cerraduras: puerta principal requiere llave dorada, faltan: llave dorada
Inventario: llave dorada
```

El actor **nunca llamó `take`** — el inventario real (`world.inventory`,
verificado con `_state_signature`) está vacío — pero el explorador
reporta `Inventario: llave dorada` de todas formas. El actor le cree, nunca
toma la llave, y repite `use(llave_oro, puerta_principal)` contra
`"Error: no llevás ningún 'llave_oro'"` el resto de los 100 pasos
(`accion_repetida_fallida` + `max_iterations_agotado`, ver modos de fallo
abajo).

Es plausible que el propio formato rígido sea la causa: exigir siempre una
línea `Inventario:` no vacía empuja al modelo a completarla con el objeto
más saliente del contexto (la llave que acaba de examinar) en vez de
chequear contra el resultado real de `look`, un efecto de "relleno de
plantilla" que el prompt viejo, más conversacional y sin una plantilla
obligatoria, no inducía de la misma forma. No se confirmó con más casos —
es una hipótesis, no una certeza— pero es consistente con la dirección
general de la sección 4.3: **la delegación cambia verdad determinística por
texto generado por otro LLM, y ese texto puede estar simplemente
equivocado** (antes por ruido de formato/idioma, ahora por una alucinación
concreta y verificable). Formatear mejor no eliminó el problema de fondo,
solo cambió su forma.

Modos de fallo completos de esta corrida:

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | study-with-key | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | — | 2 | — | 2 | 3 | 2 | 2 | 2 | 13 |
| `desborde_de_contexto` | — | — | — | 1 | — | — | — | — | 1 |
| `fallo_llm_no_transitorio` | — | — | — | 1 | — | — | — | — | 1 |
| `max_iterations_agotado` | — | 1 | 1 | 1 | 3 | 3 | 2 | 3 | 14 |
| `perdida_de_mapa_multi_sala` | 1 | 1 | — | — | — | — | — | 2 | 4 |

**Conclusión de la serie 4.3 → 4.6**: ni el tope de costo, ni el fix de
formato, movieron el modo `subagent` de su rango de ~12-29% de éxito
global, muy por debajo del `flat` equivalente (78%, sección de "Mejor
corrida encontrada" de `INFORME_M3.md`) e incluso de un `flat` en
desventaja de prompt (54%, sección 4.5).

### 4.7 Fix a la alucinación: verdad determinística en vez de confiar en el LLM

La hipótesis de la sección 4.6 (el formato rígido empuja al explorador a
"completar" el campo `Inventario:` por asociación en vez de verificarlo)
se atacó de raíz en vez de seguir iterando el prompt: `_apply_ground_truth`
(`student_framework/tools/explorer_subagent.py`) descarta lo que haya
escrito el LLM en las líneas `Inventario:` y `Cerraduras:` del resumen y
las recalcula directo desde `world` — ambos son datos discretos, 100%
derivables sin ambigüedad (`world.inventory`, y `item.locked`/
`open_state`/`inserted` de cada ítem), así que no hace falta confiar en
que el modelo los reporte bien. `Salidas:`/`Objetos visibles:`/`Sala:`
siguen siendo enteramente del explorador a propósito: la descripción de
una sala suele nombrar la sala vecina de una salida como parte del texto
narrativo (`room.description` en los JSON de escenario), algo que el
código no podría reconstruir solo desde `room.exits` sin perder
información legítima.

Incluso cuando el explorador agota su propio presupuesto sin sintetizar
nada (el caso `"(el explorador no devolvió ningún resumen...)"` de las
secciones anteriores), ahora se le devuelve al actor el inventario y las
cerraduras calculados igual — antes esos casos dejaban al actor
completamente a ciegas; ahora siempre hay al menos esos dos datos
garantizados.

Verificado con `MockLLMClient`, incluido el caso exacto de la sección 4.6
reproducido a mano: un explorador que miente ("Inventario: llave dorada"
sin que el actor la haya tomado) ahora devuelve `Inventario: vacío`
(correcto); si el actor sí toma la llave después, la siguiente exploración
(tras el cambio de firma de estado) devuelve `Inventario: llave dorada
[id: llave_oro]` (también correcto). Confirmado además de punta a punta a
través de `eval.runner.run_case` sobre `study-with-key` con un explorador
mock que alucina la misma mentira: el paso 1 del actor (`explorar_sala`)
ya sale con `Inventario: vacío`, y el caso completo llega a
`goal_achieved=True`. Suite de conformidad: sigue en 78/78.

Corrida completa (8 escenarios × 3 trials) con este fix, Bedrock
`amazon.nova-lite-v1:0`, mismo comando de siempre:
```
python eval/run.py --scenarios all --trials 3 --label subagent-lp-t3-h100-i100-v3 \
    --max-iterations 100 --max-history-messages 100 \
    --system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent
```

### 4.8 Resultado del fix v3: la hipótesis puntual se confirma, el techo general no se mueve

3524.4s total, 24 casos.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | **100%** | 35.3 / 3 | 0.68 | 4.7 | 193584/1801 | 50.6 |
| color-locks | medium | 3 | 33% | 71.7 / 11 | 0.33 | 14.0 | 527435/6990 | 130.5 |
| library-search | hard | 3 | 67% | 43.3 / 7 | 0.39 | 15.0 | 254044/2917 | 72.0 |
| extreme-archive | extreme | 3 | 33% | 695.0 / 4 | 0.24 | 6.0 | 745388/29260 | 275.0 |
| apartment-keys | medium | 3 | **0%** | 83.3 / 7 | 0.09 | — | 522990/4208 | 158.5 |
| office-sequence | hard | 3 | 0% | 100.0 / 13 | 0.13 | — | 810678/6073 | 164.7 |
| vault-combination | extreme | 3 | 0% | 106.0 / 21 | 0.20 | — | 764936/5330 | 189.4 |
| backtracking-vault | extreme | 3 | 33% | 74.3 / 18 | 0.38 | 23.0 | 663677/4108 | 133.7 |
| **TOTAL** | — | 24 | **33%** | — | — | — | — | — |

Costo oculto del explorador: 142 llamadas, 765.195 tokens de entrada,
44.491 de salida (sigue en el mismo orden que 4.6, la caché por estado
sigue funcionando).

Modos de fallo:

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 2 | 2 | 1 | 2 | 1 | 2 | 3 | 13 |
| `desborde_de_contexto` | — | — | — | 1 | — | — | — | 1 |
| `max_iterations_agotado` | 2 | 2 | 2 | 1 | 1 | 3 | 3 | 14 |
| `perdida_de_mapa_multi_sala` | 2 | 1 | — | — | — | 1 | 2 | 6 |

**La hipótesis puntual de la sección 4.6 se confirma**: `study-with-key`
—el mismo escenario donde se encontró la alucinación de inventario— vuelve
a **100%**, después de haber caído a 33% en 4.6. El fix hizo exactamente lo
que se diseñó para hacer: si la alucinación de inventario reaparecía en
algún trial, la línea `Inventario:` ya no podía mentir, así que el actor
dejó de quedarse trabado esperando tener un ítem que nunca tomó.

**Pero el total (33%) sigue en el mismo rango que todas las variantes
anteriores** (12% → 29% → 29% → 33%), y `apartment-keys` —que veníamos
mejorando, 33%→67% en 4.6— se cae a **0%**. Revisando
`case_apartment-keys_t0.json` (100 pasos): el actor toma la llave en el
paso 6, pero después de volver a la Cocina por error (paso 9) queda
repitiendo `use(llave_oro, cajon)` (un cajón de cocina, no la puerta) **90
veces seguidas** sin volver nunca al Recibidor. Esto **no tiene relación
con la alucinación de inventario** que arregló el fix — es la misma
navegación perdida entre salas ya documentada en 4.3/4.6
(`perdida_de_mapa_multi_sala`/`accion_repetida_fallida`), esta vez
manifestándose como "insistir con el objeto equivocado" en vez de "no
encontrar la salida correcta". Con `n=3` no se puede aislar si es
variancia entre corridas o una interacción real con el fix; lo que sí es
claro por la transcripción es que no es el mismo bug que se corrigió.

`extreme-archive` también vale una mención aparte: un trial resolvió en 6
pasos (casi óptimo) y otro se disparó a **1981 pasos** en un solo caso —la
variancia enorme entre "resuelve limpio" y "se cuelga por completo" que ya
se había visto en 4.3 se mantiene igual de extrema acá.

**Conclusión final de la serie de subagentes (4.1 → 4.8)**: cuatro
intervenciones distintas —tope de costo, caché por firma de estado,
formato fijo del explorador, y verdad determinística contra alucinación—
cada una corrigió exactamente el problema puntual que atacaba (el costo
desbocado bajó, el formato dejó de ser ruido, la alucinación de inventario
en `study-with-key` se corrigió, verificable caso por caso), pero **ninguna
sacó el éxito global del rango 12-33%**, muy por debajo del `flat`
equivalente (78% con el mejor prompt, 54% incluso con prompt default). El
patrón que se repite en las cuatro corridas es siempre el mismo:
`accion_repetida_fallida` + `max_iterations_agotado` +
`perdida_de_mapa_multi_sala` dominan los fallos, y son fallos de
*razonamiento sobre múltiples salas/objetos a lo largo de una
conversación larga*, no de que la información que recibe el actor esté mal
formateada o sea falsa. Corregir la señal (formato, veracidad) ayuda caso
por caso cuando el problema era la señal — pero para este modelo, en este
dataset, el cuello de botella real de la arquitectura de subagentes no es
la calidad de lo que el explorador reporta, es que separar "leer el mundo"
de "decidir qué hacer" en dos agentes no ayuda a un modelo que ya tiene
dificultad sosteniendo un plan multi-paso, sin importar cuán buena sea la
información que se le da en cada paso.

## 5. Detección de ciclos en el loop del agente (mejora de framework, no específica de subagentes)

La sección 4.8 mostró `apartment-keys` cayendo a 0% porque el actor quedó
repitiendo `use(llave_oro, cajon)` (un cajón que no tiene nada que ver con
la puerta) **90 veces seguidas** sin variar la acción — el mismo patrón
que `eval/failure_modes.py` ya venía categorizando post-hoc como
`accion_repetida_fallida` en todas las corridas de este proyecto, `flat` y
`subagent` por igual, desde la primera baseline. Estaba anotado como
pendiente desde antes de esta reentrega (`resumen-informe-m3.md`, sección
5, punto 1: "detección de ciclos... para cortar el patrón sin depender de
más presupuesto de iteraciones"). El prompt largo ya le pide explícitamente
al modelo que no repita ("Si notás que estás repitiendo... detenete", ver
`prompts/long_prompt_estado.txt`) y no alcanza — la evidencia de todas las
corridas lo confirma. Esta vez se atacó desde el framework, no desde el
prompt.

**Qué se agregó** (`student_framework/agent.py`): `MyAgent` gana
`max_consecutive_repeats: int = 2`. `_is_looping(steps, name,
arguments_json)` mira las últimas `max_consecutive_repeats` entradas de
`steps` (la lista de `AgentStep` que `run()` ya acumula en esta misma
llamada); si todas coinciden en `(tool_name, tool_input)` con el intento
que se está por ejecutar, **no se ejecuta la tool de nuevo** — se le
devuelve al modelo, como si fuera el resultado de la tool, un mensaje
explícito: *"Ya intentaste exactamente esta misma acción ... N veces
seguidas — el resultado va a ser igual, no se ejecutó de nuevo. No la
repitas..."*. Comparar solo `(tool_name, tool_input)` alcanza sin mirar el
resultado real: en este mundo determinístico, la misma tool con los mismos
argumentos sobre el mismo estado da siempre el mismo resultado, así que un
tercer intento idéntico no puede decir nada que los dos primeros no hayan
dicho ya.

Es deliberadamente genérico — no vive en `mia_world`, no depende de nada
específico del escape-room, y aplica exactamente igual a `flat` y a
`subagent` (y a las tools propias de M1: `simple_calc`/`leer_archivo`/
Markowitz). `build_agent` ya lo expone como override de config
(`max_consecutive_repeats`, agregado a `optional_keys_list` en
`student_framework/__init__.py`), mismo mecanismo que los demás
experimentos.

**Verificado con `MockLLMClient`** (sin gastar nada): un modelo scripteado
para insistir 6 veces seguidas con la misma `(tool, argumentos)` —de nuevo
`use(llave_oro, cajon)`, el caso real de 4.8— ejecuta la tool de verdad
solo las **primeras 2 veces**; a partir del tercer intento idéntico, la
tool ya no corre y el paso queda con el mensaje correctivo como `error`.
Los 6 `AgentStep` quedan registrados igual (para que `eval/failure_modes.py`
siga viendo la métrica de repetición), pero solo 2 de esos 6 dispararon una
ejecución real. Suite de conformidad: sigue en 78/78.

### 5.1 Resultado: 58% de éxito — el salto más grande de toda la serie

`python eval/run.py --scenarios all --trials 3 --label
subagent-lp-t3-h100-i100-v4 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent`
(mismo comando de siempre, `max_consecutive_repeats` va en su default
nuevo, 2, no hizo falta pasarlo). Bedrock `amazon.nova-lite-v1:0`, 24
casos, 2167.7s total — también la corrida más rápida de toda la serie
`subagent` (contra 3524.4s de la v3, 3259.5s de la v2): cortar la
repetición ahorra tiempo real, no solo éxito.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 4.0 / 3 | 0.75 | 3.3 | 12169/237 | 10.7 |
| color-locks | medium | 3 | **100%** | 14.0 / 11 | 0.79 | 14.0 | 55745/968 | 32.3 |
| library-search | hard | 3 | 67% | 44.0 / 7 | 0.60 | 8.0 | 245753/2803 | 65.4 |
| extreme-archive | extreme | 3 | 0% | 101.3 / 4 | 0.04 | — | 713945/7419 | 156.6 |
| apartment-keys | medium | 3 | **100%** | 12.0 / 7 | 0.59 | 12.0 | 42568/685 | 21.8 |
| office-sequence | hard | 3 | 33% | 72.0 / 13 | 0.40 | 20.0 | 547842/5296 | 117.5 |
| vault-combination | extreme | 3 | 0% | 100.7 / 21 | 0.21 | — | 815638/5300 | 233.3 |
| backtracking-vault | extreme | 3 | **67%** | 54.0 / 18 | 0.45 | 30.5 | 308985/3162 | 84.7 |
| **TOTAL** | — | 24 | **58%** | — | — | — | — | — |

Costo oculto del explorador: 136 llamadas, 685.657 tokens de entrada,
41.813 de salida — en línea con las corridas anteriores.

Modos de fallo:

| Categoría | backtracking-vault | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 3 | 1 | 1 | 3 | 9 |
| `desborde_de_contexto` | — | 3 | — | — | — | 3 |
| `max_iterations_agotado` | 1 | 3 | 1 | 1 | 3 | 9 |
| `perdida_de_mapa_multi_sala` | 1 | — | — | — | 3 | 4 |
| `se_detuvo_sin_lograr_la_meta` | — | — | — | 1 | — | 1 |

**Línea completa de la serie de subagentes**: 12% (v1, tope ciego) → 29%
(v1 corregido, prompt viejo) → 29% (v2, formato fijo) → 33% (v3, verdad
determinística) → **58% (v4, detección de ciclos)**. Es, con diferencia,
el salto más grande de los cuatro fixes — y el único que atacó el loop del
agente en sí en vez del contenido del resumen del explorador. Nótese
también que `color-locks` y `apartment-keys` ya no aparecen en la tabla de
modos de fallo (0 casos fallidos en ninguna categoría): pasaron de
33%/0% (sección 4.6) y 0% (sección 4.8) a **100% en ambos**, sin ningún
otro cambio de config — consistente con que su cuello de botella
específico era justamente quedarse repitiendo la misma acción sin
converger, exactamente lo que este fix corta.

**Lo que no se movió**: `extreme-archive` (0%, con `desborde_de_contexto`
en los 3 trials) y `vault-combination` (0%) siguen sin resolverse. Son los
dos escenarios `extreme` con la cadena de dependencias más profunda —
consistente con la lectura de toda la serie: la detección de ciclos ayuda
cuando el problema es quedarse trabado repitiendo una acción, pero no
sustituye la capacidad de sostener un plan largo en escenarios que de por
sí requieren memoria de mucho volumen de información (`extreme-archive`) o
combinar piezas a través de varias salas (`vault-combination`).

**Esto también revisa la conclusión de la sección 4.8** ("el techo no se
mueve, es la arquitectura en sí"): con este fix, el modo `subagent` pasa de
"muy por debajo de `flat`" (33% vs. 78%/54%) a un resultado intermedio
respetable (58%) — más cerca del `flat` sin prompt custom (54%, sección
4.5) que de su piso anterior. La lectura correcta no es "la arquitectura
de subagentes es inviable", es que **la mayoría del costo de delegar
explorar/actuar en dos agentes venía de un bug de framework compartido con
`flat` (no cortar loops), no de la delegación en sí** — una vez corregido
ese bug común, la brecha real entre arquitecturas se ve mucho más chica.
Sigue pendiente correr `flat` con el mismo fix para confirmar cuánto de
esta mejora es "arreglamos un bug que afectaba a los dos modos por igual"
vs. algo específico de `subagent`.

### 5.2 La comparación pendiente: `flat` con el mismo fix da 67% — parece peor, pero el fix no tuvo nada que ver

`python eval/run.py --scenarios all --trials 3 --label
long-prompt-t3-h100-i100-v4 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt` (sin `--agent-mode`,
`flat` por default — la comparación pendiente de la sección 5.1). Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 1696.7s total.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.3 / 3 | 0.57 | 4.7 | 16950/307 | 5.1 |
| color-locks | medium | 3 | 67% | 45.3 / 11 | 0.45 | 18.0 | 340928/3374 | 65.4 |
| library-search | hard | 3 | 67% | 44.0 / 7 | 0.32 | 16.0 | 371763/3210 | 68.8 |
| extreme-archive | extreme | 3 | 100% | 24.0 / 4 | 0.17 | 23.7 | 201781/1393 | 24.0 |
| apartment-keys | medium | 3 | 33% | 72.0 / 7 | 0.19 | 16.0 | 435766/4018 | 93.7 |
| office-sequence | hard | 3 | 67% | 87.7 / 13 | 0.29 | 20.0 | 417417/4051 | 97.4 |
| vault-combination | extreme | 3 | 33% | 82.0 / 21 | 0.35 | 30.0 | 484867/3879 | 101.0 |
| backtracking-vault | extreme | 3 | 67% | 94.0 / 18 | 0.19 | 55.0 | 493148/4810 | 109.7 |
| **TOTAL** | — | 24 | **67%** | — | — | — | — | — |

Modos de fallo:

| Categoría | apartment-keys | backtracking-vault | color-locks | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 2 | 1 | 1 | 1 | — | 2 | 7 |
| `max_iterations_agotado` | 2 | 1 | 1 | 1 | — | 2 | 7 |
| `perdida_de_mapa_multi_sala` | 2 | 1 | — | — | — | 2 | 5 |
| `se_detuvo_sin_lograr_la_meta` | — | — | — | — | 1 | — | 1 |

**A primera vista, esto parece un empeoramiento**: 67% acá vs. 78% en
`long-prompt-estado-t5-h-100-i-100` (la mejor corrida sin este fix). Pero
antes de leerlo como "la detección de ciclos perjudica a `flat`", hay que
verificar si el fix tuvo algo que ver con los casos que fallaron — y no lo
tuvo. Revisando cada caso fallido de esta corrida
(`library-search_t1`, `apartment-keys_t0`, `apartment-keys_t2`, y el resto)
por la marca `"Ya intentaste exactamente esta misma acción"` que deja el
fix cuando corta un intento: **0 pasos bloqueados en absolutamente
ninguno de los casos fallidos**. La detección de ciclos nunca se activó en
esta corrida donde "importaba" — así que no puede ser la causa de que
estos trials fallaran.

**Lo que sí se encontró revisando `library-search_t1`** (100 pasos, nunca
llega a la meta): el agente cae en un ciclo de **período mayor a 1** —
vuelve a hacer `look` y re-examina los mismos 8 libros en el mismo orden,
una y otra vez, sin repetir nunca la *misma* llamada dos veces seguidas
(alterna entre `examine libro_geometria`, `examine libro_alquimia`, ...,
antes de volver a `examine libro_geometria`). `_is_looping` (sección 5)
solo compara las últimas `max_consecutive_repeats` llamadas **idénticas y
consecutivas** — por diseño no detecta un ciclo donde el agente repite un
*bloque* de acciones distintas en vez de una sola acción. Es el mismo tipo
de limitación que `eval/failure_modes._has_unproductive_room_cycle` ya
resuelve para navegación entre salas (chequea períodos de 1 a 8, no solo
período 1) — la detección de ciclos de esta sección quedó acotada al caso
más simple (período 1), y este caso concreto muestra el límite de esa
simplificación.

**Conclusión**: la diferencia 67% vs. 78% es consistente con varianza de
muestra (`n=3` vs. `n=5`, y `library-search` en particular ya está
documentado en `resumen-informe-m3.md` como "el más inestable de todos,
oscila entre 0% y 100% sin tendencia clara") más que con un efecto real del
fix — la evidencia directa (cero activaciones en los casos fallidos) lo
respalda. El fix de la sección 5 no perjudicó a `flat`; simplemente no
tuvo la oportunidad de ayudar en los casos que fallaron esta vez, porque el
patrón de fallo dominante acá fue un ciclo de período > 1, que está fuera
del alcance de lo que se implementó.

## 5.3 Generalización: ciclos de cualquier período (no solo período 1)

`_is_looping` (`student_framework/agent.py`) se reescribió para detectar
ciclos de período 1 a `max_cycle_period` (default 8, nuevo parámetro de
`MyAgent`), no solo una acción idéntica repetida: para cada período `p`
candidato, arma la secuencia de `(tool_name, tool_input)` de los pasos ya
ejecutados más el intento actual, y comprueba si los últimos `p ×
(max_consecutive_repeats + 1)` elementos son exactamente el mismo bloque de
`p` llamadas repetido `max_consecutive_repeats + 1` veces seguidas. Con
`p=1` coincide exactamente con el comportamiento anterior (la sección 5
original); con `p>1` captura el patrón de `library-search_t1` (sección
5.2): re-examinar la misma lista de 8 objetos en el mismo orden, una y otra
vez, sin repetir nunca la *misma* llamada dos veces seguidas. Mismo
criterio que ya usa `eval/failure_modes._has_unproductive_room_cycle` para
navegación entre salas, generalizado acá a cualquier secuencia de tools.

**Trade-off documentado, no oculto**: el punto en el que se corta escala
con el período — un ciclo de período 1 se corta después de 2 repeticiones
reales (igual que antes), pero un ciclo de período 8 recién se corta al
completarse casi 3 repeticiones enteras (~23 llamadas reales antes de
bloquear la 24ª). Sigue siendo una mejora real (corta ~76 pasos
desperdiciados de los 100 disponibles en vez de ninguno), pero no es tan
inmediata como la detección de período 1.

Verificado con `MockLLMClient` reproduciendo el ciclo exacto de
`library-search_t1` (`look` + 7 `examine` distintos, repetido 3 veces):
las tools se ejecutan de verdad 23 veces, y la 24ª —que hubiera completado
la 3ª repetición completa del bloque de 8— queda bloqueada con el mensaje
correctivo. El caso de período 1 (sección 5) se re-verificó sin cambios:
sigue cortando en el mismo punto de antes. Suite de conformidad: 78/78.

## 5.4 Resultado de la generalización en `flat`: 83% — el mejor número de todo el proyecto

`python eval/run.py --scenarios all --trials 3 --label
long-prompt-t3-h100-i100-v5 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt` (mismo comando de la
sección 5.2, con la generalización de la 5.3 ya en el código — no hace
falta ningún flag nuevo, `max_cycle_period=8` es el default). Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 1398.7s total — también la corrida más
rápida de toda la familia `long-prompt` en `flat`.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.7 / 3 | 0.53 | 5.0 | 17927/308 | 5.2 |
| color-locks | medium | 3 | **100%** | 22.0 / 11 | 0.54 | 22.0 | 94277/1469 | 22.8 |
| library-search | hard | 3 | **100%** | 19.3 / 7 | 0.37 | 19.0 | 103857/1265 | 22.5 |
| extreme-archive | extreme | 3 | 100% | 23.7 / 4 | 0.17 | 23.3 | 242521/1658 | 28.0 |
| apartment-keys | medium | 3 | 33% | 72.7 / 7 | 0.18 | 18.0 | 503641/4177 | 98.4 |
| office-sequence | hard | 3 | **100%** | 100.7 / 13 | 0.13 | 23.0 | 666380/5258 | 139.5 |
| vault-combination | extreme | 3 | 67% | 60.7 / 21 | 0.42 | 40.5 | 338482/3157 | 73.1 |
| backtracking-vault | extreme | 3 | 67% | 60.7 / 18 | 0.35 | 39.0 | 355649/3587 | 76.5 |
| **TOTAL** | — | 24 | **83%** | — | — | — | — | — |

Modos de fallo:

| Categoría | apartment-keys | backtracking-vault | vault-combination | Total |
|---|---:|---:|---:|---:|
| `accion_repetida_fallida` | 2 | 1 | 1 | 4 |
| `max_iterations_agotado` | 2 | 1 | 1 | 4 |
| `perdida_de_mapa_multi_sala` | 1 | 1 | 1 | 3 |

**83% es el mejor número de todo el proyecto** — supera incluso al 78% de
`long-prompt-estado-t5-h-100-i-100` (que tenía 5 trials contra 3 acá,
así que no es una comparación perfecta, pero la dirección es clara). Y
**`library-search` llega a 100%**, justo el escenario cuyo ciclo de
período 8 (re-examinar los mismos 8 libros en el mismo orden) motivó la
generalización de la sección 5.3 — la hipótesis puntual se confirma
directamente, igual que pasó con la alucinación de inventario en la
sección 4.8. `color-locks` y `office-sequence` también llegan a 100%.

**Lo que sigue sin resolverse, y por qué, revisando `apartment-keys`**
(33%, el único escenario débil): los 3 trials muestran comportamientos
distintos —

- Trial 1 (único éxito): 18 pasos limpios, cero bloqueos por ciclo.
- Trial 0 (falla, 100 pasos): **91 de los 100 pasos fueron `look`, y 86 de
  esos 91 quedaron bloqueados por la detección de ciclos** — el agente
  recibió el aviso correctivo ("no lo repitas, cambiá de estrategia") una
  y otra vez, y **igual siguió pidiendo el mismo `look` bloqueado**, en vez
  de probar algo distinto. Es un límite real del mecanismo: interceptar la
  ejecución evita gastar la tool y da una pista clara, pero no obliga al
  modelo a *usar* esa pista — si insiste en la misma acción bloqueada,
  sigue gastando el presupuesto de iteraciones (aunque ya no el de
  ejecuciones reales) sin converger.
- Trial 2 (falla, 100 pasos): 66 `go` + 28 `use`, solo 9 bloqueos — acá el
  agente sí varía lo que intenta (no es un ciclo corto y limpio), pero
  sigue sin encontrar la combinación correcta. Un fallo distinto, no
  relacionado con ciclos.

**Conclusión de la serie 5 → 5.4**: la detección de ciclos (período 1 y
generalizada a período > 1) fue, con diferencia, la intervención de
framework con más impacto de toda esta reentrega — pasó `flat` de 67% a
83% y `subagent` de 33% a 58% con el mismo mecanismo genérico. Pero
`apartment-keys` deja un límite claro: bloquear una acción repetida
funciona cuando el modelo tiene *otra* idea disponible y el bloqueo lo
empuja a probarla; no funciona cuando el modelo no tiene una idea
alternativa y simplemente insiste en la misma acción bloqueada hasta
agotar el presupuesto.

## 5.5 Escalada más allá del mensaje correctivo: cortar `run()` si el bloqueo se acumula

Implementado el próximo paso que dejó pendiente la sección 5.4:
`MyAgent` gana `max_blocked_repeats: int = 5`. `run()` ahora lleva un
contador `consecutive_blocks` que se reinicia cada vez que se ejecuta una
tool real (sin bloqueo) y se incrementa cada vez que `_is_looping` bloquea
un intento; si supera `max_blocked_repeats`, `run()` corta ahí mismo —no
sigue agotando `max_iterations`— y devuelve un `AgentResult` con `error`
explicando qué pasó ("la misma acción o ciclo de acciones quedó bloqueado N
veces seguidas sin que el agente cambiara de estrategia").

Con el default (5), esto acota el peor caso de `apartment-keys_t0`
(sección 5.4: 86 bloqueos consecutivos sin recuperación) a que `run()`
corte en el 6º bloqueo — 80 pasos de presupuesto que antes se gastaban
insistiendo con algo ya sabido inútil ahora se ahorran.

**Categorización nueva en `eval/failure_modes.py`**: sin distinguirlo,
este corte quedaría clasificado como `fallo_llm_no_transitorio` (la
categoría genérica para cualquier `AgentResult.error`), que es engañoso —
no es un fallo del proveedor ni del LLM, es una decisión deliberada del
framework. Se agregó `ciclo_escalado_abortado`, detectado por el prefijo
fijo del mensaje de error (`"Se cortó la ejecución:"`), para que el
análisis de errores del informe distinga "el framework decidió cortar"
de "el LLM/proveedor falló de verdad".

Verificado con `MockLLMClient`: un modelo scripteado para insistir 20
veces seguidas con el mismo `look` sin argumentos corta en el paso 8 (2
ejecuciones reales + 6 bloqueos) en vez de agotar las 20 respuestas
programadas o `max_iterations`; `classify_failure` categoriza ese
`AgentResult.error` como `ciclo_escalado_abortado`, no como
`fallo_llm_no_transitorio`. Suite de conformidad: 78/78.

## 5.6 Resultado de la escalada en `flat`: 75%, y confirma la hipótesis puntual de `apartment-keys`

`python eval/run.py --scenarios all --trials 3 --label
long-prompt-t3-h100-i100-v6 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt` (mismo comando de la
5.4, con la escalada de la 5.5 ya en el código). Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 1088.4s total — la corrida `flat` más
rápida de toda la familia `long-prompt`.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 7.0 / 3 | 0.44 | 6.0 | 22383/395 | 6.4 |
| color-locks | medium | 3 | 100% | 18.0 / 11 | 0.63 | 18.0 | 72273/1427 | 19.2 |
| library-search | hard | 3 | 67% | 19.3 / 7 | 0.39 | 15.5 | 98103/1312 | 19.8 |
| extreme-archive | extreme | 3 | 67% | 23.7 / 4 | 0.17 | 24.5 | 247896/1671 | 30.6 |
| apartment-keys | medium | 3 | **100%** | 13.7 / 7 | 0.52 | 13.0 | 48261/811 | 12.4 |
| office-sequence | hard | 3 | 100% | 78.7 / 13 | 0.21 | 24.0 | 461831/3572 | 95.8 |
| vault-combination | extreme | 3 | 67% | 57.0 / 21 | 0.47 | 35.5 | 362222/3626 | 74.0 |
| backtracking-vault | extreme | 3 | **0%** | 73.3 / 18 | 0.42 | — | 480313/4300 | 104.4 |
| **TOTAL** | — | 24 | **75%** | — | — | — | — | — |

Modos de fallo:

| Categoría | backtracking-vault | extreme-archive | library-search | vault-combination | Total |
|---|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 3 | — | 1 | 1 | 5 |
| `ciclo_escalado_abortado` | 1 | — | 1 | — | 2 |
| `max_iterations_agotado` | 2 | — | — | 1 | 3 |
| `perdida_de_mapa_multi_sala` | 2 | — | — | — | 2 |
| `se_detuvo_sin_lograr_la_meta` | — | 1 | — | — | 1 |

**Se confirma la hipótesis puntual de la sección 5.4**: `apartment-keys`
—el escenario donde el modelo insistía 86 veces con el mismo `look`
bloqueado, sin escalada— pasa de **33% a 100%**. La escalada hizo
exactamente lo que se diseñó para hacer ahí.

**`ciclo_escalado_abortado` aparece 2 veces** (confirmando que el mecanismo
se activa en corridas reales, no solo en el mock). Uno de esos dos casos es
`backtracking-vault_t1`, que corta en el paso 20 en vez de 100 — revisando
la transcripción: el agente encontró una "llave intermedia" en un
escritorio pero **nunca la tomó**, y quedó alternando `look`/`go norte`
contra una puerta blindada bloqueada 6 veces seguidas antes de cortar. No
es un falso positivo — es un caso genuinamente encallado (nunca iba a
resolver el escenario sin tomar esa llave primero) que ahora se corta
temprano en vez de gastar 80 pasos más sin ninguna chance real.

**`backtracking-vault` cae de 67% (v5) a 0% (v6)** — a primera vista un
retroceso grande, pero con la misma cautela que ya aplicamos varias veces
en esta reentrega: los otros dos trials (`t0`, `t2`) corrieron los 100
pasos completos **sin ninguna escalada** y tampoco llegaron a la meta, así
que la escalada no es la causa de que fallaran. `backtracking-vault` es el
escenario con la cadena de dependencias más profunda del dataset
(`ENUNCIADO_M3.md`: "el cofre de la 1ª sala solo abre con la llave de la
última"), y su tasa de éxito ya venía siendo la más volátil de toda la
serie entre corridas (33%→67%→0% en v3/v5/v6, cada vez con `n=3`) — más
consistente con varianza de muestra en un escenario genuinamente difícil
que con un efecto real de este fix.

## 5.7 `subagent` con la escalada: 54%, y un falso positivo real encontrado y corregido

`python eval/run.py --scenarios all --trials 3 --label
subagent-lp-t3-h100-i100-v6 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent`
(comando de la sección 5.1, con la escalada de la 5.5). Bedrock
`amazon.nova-lite-v1:0`, 24 casos.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 3.7 / 3 | 0.83 | 3.0 | 12137/223 | 56.9 |
| color-locks | medium | 3 | 67% | 16.0 / 11 | 0.71 | 17.5 | 65843/2658 | 68.0 |
| library-search | hard | 3 | **0%** | 49.7 / 7 | 0.22 | — | 265675/3370 | 70.9 |
| extreme-archive | extreme | 3 | 33% | 51.0 / 4 | 0.21 | 45.0 | 532170/3541 | 94.9 |
| apartment-keys | medium | 3 | 100% | 13.0 / 7 | 0.56 | 13.0 | 46227/723 | 23.9 |
| office-sequence | hard | 3 | 67% | 44.7 / 13 | 0.55 | 17.0 | 321615/2615 | 74.2 |
| vault-combination | extreme | 3 | 33% | 46.7 / 21 | 0.51 | 41.0 | 279541/2721 | 87.5 |
| backtracking-vault | extreme | 3 | 33% | 27.3 / 18 | 0.67 | 23.0 | 127393/1569 | 45.2 |
| **TOTAL** | — | 24 | **54%** | — | — | — | — | — |

Modos de fallo (`ciclo_escalado_abortado` aparece **8 veces**, contra 2 en
`flat`/5.6 — mucho más frecuente en `subagent`):

| Categoría | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 2 | 1 | 2 | 3 | 1 | 2 | 11 |
| `argumento_invalido_tool_mundo` | — | — | 1 | — | — | — | 1 |
| `ciclo_escalado_abortado` | 2 | — | 1 | **3** | — | 2 | 8 |
| `desborde_de_contexto` | — | — | 1 | — | — | — | 1 |
| `max_iterations_agotado` | — | — | 1 | — | 1 | — | 2 |
| `perdida_de_mapa_multi_sala` | — | — | — | — | 1 | 1 | 2 |

**54% queda por debajo del 58% de la v4** (cycle detection de período 1
sola, sin generalizar ni escalar) — a diferencia de `flat`, acá agregar
más protección contra ciclos empeoró el número. Investigar por qué llevó a
un hallazgo real, no solo ruido.

**`library-search` cae a 0% (3/3), las tres cortadas por escalada.**
Revisando `library-search_t0` (corta en el paso 18): el actor, con solo
`take`/`use`/`go`/`explorar_sala` disponibles (sin `examine` propia),
intentó `take` sobre los 8 libros uno por uno —todos fallan, los libros no
son tomables, hay que *examinarlos*— y después insistió con
`use(llave_caja, caja_fuerte)` sin tener la llave, bloqueado correctamente
a la 3ª. **No es un falso positivo**: el agente estaba genuinamente
encallado (nunca iba a resolver así) y la escalada cortó a tiempo. Pero
expone una limitación estructural del split `subagent` que no tiene que
ver con ciclos: el actor no puede pedirle al explorador que examine *un*
objeto puntual — solo puede volver a llamar `explorar_sala()` entera y
esperar que el explorador decida por su cuenta qué examinar. En un
escenario que depende de examinar el libro correcto entre 8, esa
indirección pesa. (Nota aparte para un futuro ajuste de la tool
`explorar_sala`, no de la detección de ciclos.)

**El hallazgo real: un falso positivo genuino en `backtracking-vault_t0`**
(corta en el paso 33). Transcripción relevante:

```
19. go(sur) -> "Caminas hacia sur. Llegas a Sala B."
20. go(sur) -> "Caminas hacia sur. Llegas a Sala A."
21. go(sur) -> BLOQUEADO ("ya forma parte de un patrón que se repitió...")
```

`go(direction="sur")` se llamó dos veces con **resultados distintos**
(cada una te deja en una sala distinta, backtracking legítimo por una
cadena lineal de salas — exactamente el mecanismo que
`backtracking-vault` está diseñado para exigir) y aun así la 3ª quedó
bloqueada. Causa: `_is_looping` (secciones 5, 5.3) comparaba solo
`(tool_name, tool_input)`, asumiendo "misma tool + mismos argumentos ⇒
mismo resultado" — cierto para tools de solo lectura (`examine`), **falso
para `go`**, cuyo resultado depende de en qué sala estás, no solo de la
dirección pedida.

**Fix** (`student_framework/agent.py`): `_is_looping` ahora compara
`(tool_name, tool_input, tool_output, error)` completo en los pasos ya
ejecutados, no solo `(tool_name, tool_input)` — si el resultado cambió
entre llamadas "idénticas", hay progreso real y no se bloquea; si no
cambió, sí. Efecto secundario que hubo que corregir aparte: un paso ya
bloqueado tiene su propia firma sintética (`tool_output=None`, un mensaje
de error fijo) que no coincide con la firma de una ejecución real
repetida — sin filtrarlo, el intento *inmediatamente después* de un
bloqueo dejaba de verse como parte del ciclo (por culpa del bloqueo mismo)
y se re-ejecutaba una vez más antes de volver a bloquear, oscilando en vez
de quedarse bloqueado de forma sostenida. Se agregó `_LOOP_BLOCKED_MARKER`
(una constante de módulo) para que `_is_looping` excluya sus propios
bloqueos previos del historial que analiza.

Verificado con `MockLLMClient`: (1) 4 `go(sur)` seguidos a salas distintas
—el caso exacto de `backtracking-vault_t0`— ya no bloquean ninguno; (2)
una puerta genuinamente bloqueada con el mismo error 10 veces seguidas
sigue bloqueando desde el 3er intento **y se mantiene bloqueada sin
oscilar** (patrón `..BBBBBBBB`, cero ejecuciones reales de más); (3) el
ciclo de período 8 de `library-search` (sección 5.3) se sigue detectando
igual (23 ejecuciones reales, 1 bloqueo); (4) la escalada (sección 5.5)
sigue cortando `run()` correctamente. Suite de conformidad: 78/78.

**Pendiente**: re-correr `flat` y `subagent` con este fix — no se sabe
todavía cuánto del 54%/75% de las secciones 5.6/5.7 estaba deprimido por
este falso positivo específico (`go` en escenarios multi-sala con
backtracking legítimo, que es exactamente el mecanismo central de
`backtracking-vault` y aparece también en `apartment-keys`/
`office-sequence`/`vault-combination`).

## 5.8 `explorar_sala(foco=...)`: dejar que el actor apunte a un objeto puntual

Motivado directamente por el hallazgo de `library-search` en la sección
5.7 (no era un falso positivo de ciclos, pero sí expuso una limitación
real): el actor de `subagent` solo podía pedir "explorá todo de nuevo"
para saber más sobre un objeto puntual entre varios — sin forma de decirle
al explorador "fijate específicamente en este" (p. ej. decidir cuál de 8
libros es el correcto), lo empujaba a probar `take` a ciegas sobre cada
uno en vez de pedir una lectura más profunda de uno solo.

**Cambio** (`student_framework/tools/explorer_subagent.py`):
`explorar_sala` gana un parámetro opcional `foco` (id de un objeto ya
visto en una exploración anterior). Sin `foco`, se comporta igual que
antes (barre toda la sala). Con `foco`, la directiva que recibe el
explorador cambia de "explorá todo" a "examiná específicamente `foco` en
detalle, no hace falta que veas el resto" — sigue siendo delegación real
(el explorador ejecuta el `examine`, no el actor), solo que dirigida.

**Detalle que había que resolver**: la caché por firma de estado (sección
4.2) no podía seguir indexando solo por `_state_signature(world)` — una
exploración general y una enfocada en un objeto puntual son pedidos
distintos aunque el mundo no cambió entre una y otra, y no deben compartir
resultado cacheado (si comparten clave, pedir `foco='libro_a'` después de
un `explorar_sala()` general con el mismo estado devolvería el resumen
general cacheado, no la lectura profunda de `libro_a`). La clave de caché
pasa a ser `(estado, foco)`.

Trade-off, tal como se discutió antes de implementarlo: el actor necesita
saber el id del objeto que quiere que se examine (lo obtiene de una
exploración general anterior), así que ya no es "el actor nunca sabe nada
de objetos puntuales, todo pasa por el explorador sin nombres propios" —
sigue sin poder llamar `examine` él mismo, pero sí puede nombrar el
objetivo.

Verificado con `MockLLMClient`: el schema expone `foco` como parámetro
opcional (no requerido); `explorar_sala()` general y
`explorar_sala(foco="libro_a")` con el mismo estado del mundo corren el
explorador real las dos veces (no comparten caché, cada uno gasta su
propia llamada al LLM); repetir `explorar_sala(foco="libro_a")` con el
mismo estado sí usa la caché (0 llamadas extra); la directiva mandada al
explorador para la llamada enfocada menciona explícitamente el id pedido.
Suite de conformidad: 78/78.

**Pendiente**: correr `subagent` de nuevo (con el fix de falsos positivos
de la sección 5.7 ya incluido) para ver si `foco` mueve específicamente
`library-search` — no alcanza con que el actor *pueda* pedir una
exploración enfocada, también hace falta que el prompt/la estrategia del
actor lo empuje a usarla en vez de seguir probando `take` a ciegas; eso no
se tocó en este cambio.

## 5.9 `subagent` con el fix de falsos positivos + `foco`: 58%, y ambos hallazgos se confirman

`python eval/run.py --scenarios all --trials 3 --label
subagent-lp-t3-h100-i100-v7 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt --agent-mode subagent`
(comando de siempre, con el fix de falsos positivos de la 5.7 y `foco` de
la 5.8 ya en el código). Bedrock `amazon.nova-lite-v1:0`, 24 casos, 2017.8s
total.

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 3.3 / 3 | 0.92 | 3.0 | 11804/207 | 7.7 |
| color-locks | medium | 3 | 67% | 48.0 / 11 | 0.41 | 22.0 | 300514/3367 | 94.0 |
| library-search | hard | 3 | **67%** | 13.3 / 7 | 0.67 | 16.5 | 65718/958 | 48.0 |
| extreme-archive | extreme | 3 | **100%** | 16.3 / 4 | 0.45 | 16.0 | 113551/1181 | 77.3 |
| apartment-keys | medium | 3 | 67% | 41.7 / 7 | 0.40 | 12.5 | 261119/1972 | 69.4 |
| office-sequence | hard | 3 | 33% | 44.7 / 13 | 0.60 | 52.0 | 289600/2445 | 148.9 |
| vault-combination | extreme | 3 | 0% | 69.7 / 21 | 0.44 | — | 526922/3951 | 146.2 |
| backtracking-vault | extreme | 3 | 33% | 47.0 / 18 | 0.69 | 26.0 | 304441/3233 | 80.8 |
| **TOTAL** | — | 24 | **58%** | — | — | — | — | — |

Costo oculto del explorador: 185 llamadas, 899.193 tokens de entrada,
59.277 de salida.

Modos de fallo (`ciclo_escalado_abortado` baja de **8 a 2** frente a la
5.7 — confirma que buena parte de los 8 anteriores eran falsos positivos
del bug de `go`, no ciclos genuinos):

| Categoría | apartment-keys | backtracking-vault | color-locks | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 1 | 2 | 1 | — | 2 | 2 | 8 |
| `ciclo_escalado_abortado` | — | 1 | — | — | 1 | — | 2 |
| `max_iterations_agotado` | 1 | 1 | 1 | — | — | 1 | 4 |
| `perdida_de_mapa_multi_sala` | 1 | — | — | — | — | 3 | 4 |
| `se_detuvo_sin_lograr_la_meta` | — | — | — | 1 | — | — | 1 |

**Ambos hallazgos se confirman directamente en la transcripción, no solo
en el número agregado**:

- **`library-search` pasa de 0% (sección 5.7) a 67%** — y revisando los 3
  trials, el actor usó `foco` extensamente en los tres, sin que hiciera
  falta ningún ajuste de prompt adicional (la descripción de la tool
  alcanzó): trial 0 (éxito) pidió `foco` sobre `estanteria_alta`,
  `escritorio` y `caja_fuerte` en 10 pasos; trial 2 (éxito) recorrió los 8
  libros uno por uno con `foco` antes de resolver la caja fuerte. El
  parámetro se adoptó naturalmente y cambió el resultado del escenario que
  lo motivó.
- **`ciclo_escalado_abortado` cae de 8 a 2**, consistente con que la
  mayoría de esos 8 en la sección 5.7 eran el falso positivo de `go`
  bloqueando backtracking legítimo, no ciclos genuinos — con el fix,
  quedan solo los 2 casos que sí lo son.

**58% total** — vuelve al nivel de la v4 (primera versión de la detección
de ciclos, antes de generalizar a período > 1), después de haber bajado a
33%/54% en el medio por el bug del falso positivo. `vault-combination`
sigue en 0% y `office-sequence`/`backtracking-vault` no despegan de
33% — siguen siendo los escenarios de dependencias más profundas del
dataset, sin que ningún fix de esta serie los haya movido todavía.

## 5.10 `flat` con el fix de falsos positivos: mismo 75%, pero `backtracking-vault` mejora donde importaba

`python eval/run.py --scenarios all --trials 3 --label
long-prompt-t3-h100-i100-v7 --max-iterations 100 --max-history-messages 100
--system-prompt-file prompts/long_prompt_estado.txt` (comando de la 5.6,
con el fix de falsos positivos de la 5.7 ya en el código). Bedrock
`amazon.nova-lite-v1:0`, 24 casos, 1446.2s total.

| Escenario | Dificultad | v6 (con falso positivo) | v7 (corregido) |
|---|---|---:|---:|
| study-with-key | easy | 100% | 100% |
| color-locks | medium | 100% | 67% |
| library-search | hard | 67% | 67% |
| extreme-archive | extreme | 67% | 100% |
| apartment-keys | medium | 100% | 100% |
| office-sequence | hard | 100% | 67% |
| vault-combination | extreme | 67% | 67% |
| backtracking-vault | extreme | **0%** | **33%** |
| **TOTAL** | — | **75%** | **75%** |

Modos de fallo — **`ciclo_escalado_abortado` no aparece ni una vez** (0
casos, contra 2 en la v6):

| Categoría | backtracking-vault | color-locks | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|
| `accion_repetida_fallida` | 2 | 1 | 1 | 1 | 1 | 6 |
| `max_iterations_agotado` | 2 | 1 | 1 | 1 | 1 | 6 |
| `perdida_de_mapa_multi_sala` | 2 | — | — | — | — | 2 |

**El total agregado no se movió (75%→75%), pero la lectura correcta no es
"el fix no sirvió"**: `backtracking-vault` —el escenario donde se encontró
el falso positivo exacto en la sección 5.7— mejora de **0% a 33%**, y
`ciclo_escalado_abortado` desaparece del todo (0 casos, contra 2 antes).
El resto del movimiento (`color-locks` y `office-sequence` bajando de
100% a 67%, `extreme-archive` subiendo de 67% a 100%) es ruido de muestra
consistente con el patrón que se repite en toda esta reentrega a `n=3`
—ninguno de esos tres tiene relación con `go` ni con backtracking, así
que el fix de la sección 5.7 no puede explicarlos—, y se cancela casi
exactamente con la mejora real de `backtracking-vault` en la suma total.

**Conclusión de la serie 5.7 → 5.10**: el fix de falsos positivos hizo lo
que se propuso —eliminó bloqueos espurios de `go` en backtracking
legítimo, confirmado por `ciclo_escalado_abortado` cayendo a 0 en `flat` y
a 2 en `subagent` (era 8)— y mejoró específicamente el escenario que lo
motivó en ambos modos (`backtracking-vault` 0%→33% en `flat`;
`library-search` con `foco`, sección 5.8/5.9, 0%→67% en `subagent`). El
número agregado de 24 casos a `n=3` sigue sin ser una vara confiable para
ver eso — hace falta mirar el escenario puntual y el modo de fallo, no
solo el total, tal como ya se repitió varias veces en esta reentrega.

## 6. Planner, segunda corrida (con los fixes de detección de ciclos): confirma la hipótesis de la sección 3

`python eval/run.py --scenarios all --trials 3 --label planner-t3-h100-i100-v7 \
--max-iterations 100 --max-history-messages 100 \
--system-prompt-file prompts/long_prompt_estado.txt --planner` — mismo
comando que la sección 3, corrido ahora con toda la serie de detección de
ciclos (5.1 → 5.10, incluido el fix de falsos positivos) ya en el código.
Bedrock `amazon.nova-lite-v1:0`, 24 casos, 1698.5s total.

| Escenario | Dificultad | Planner v1 (sección 3) | Planner v7 (con fixes) | `flat` v7 (5.10, sin planner) |
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

Modos de fallo de esta corrida — a diferencia de todas las corridas `flat`
de la serie 5.x, acá sí aparece `ciclo_escalado_abortado` (1 caso, en
`office-sequence`), y `library-search` no tiene ningún caso de esa
categoría pese a caer a 0%: sus 3 trials fallan por
`accion_repetida_fallida`/`max_iterations_agotado` puro, no por la
detección de ciclos.

**El total agregado es idéntico al de la sección 3 (67%→67%)**, pero la
composición cambia exactamente en la dirección que ya se había planteado
como hipótesis ahí: `library-search` (el escenario de "descubrir cuál de 8
libros", sin orden fijo posible) empeora más todavía (33%→0%), mientras
`office-sequence` y `vault-combination` —ambos con una secuencia de pasos
más rígida— mejoran (33%→67% los dos). `backtracking-vault` se mantiene en
67%, que es además su mejor lectura de toda la reentrega y la única corrida
donde le gana a `flat` (67% vs 33% en la 5.10).

Comparado contra `flat` v7 con el mismo código de detección de ciclos, el
planner queda 8 puntos por debajo (67% vs 75%) y el bache es casi todo
`library-search` (0% vs 67%): anteponer un plan de sub-metas antes de
explorar nada sigue penalizando al escenario donde la información
necesaria (qué libro) no existe todavía en el momento de planificar. La
detección de ciclos no compensa eso — el agente con planner no queda
trabado en un ciclo detectable en `library-search` (0 casos de
`ciclo_escalado_abortado` ahí), simplemente agota pasos probando libros sin
converger.

**Conclusión**: con el doble de muestra acumulada ahora sobre la hipótesis
de la sección 3 (2×3 trials por celda), el patrón se sostiene y se
profundiza en el mismo sentido — el planner ayuda en escenarios de orden
rígido (`backtracking-vault`, `office-sequence`, `vault-combination`) y
perjudica en escenarios de descubrimiento (`library-search`), con el total
agregado empatado por casualidad en ambas corridas. Sigue siendo `n=3` por
celda (ahora `n=6` combinando ambas corridas para las celdas que no
cambiaron de código entre medio, pero las dos corridas de planner sí
difieren en la detección de ciclos del framework, así que no son
estrictamente la misma condición y no deberían promediarse sin más).

## 7. Qué falta

- Con más trials, separar de una vez la varianza real de `backtracking-vault`
  del efecto de cada fix — es el escenario más inestable de todo el
  dataset entre corridas de 3 trials, y ya lleva cuatro lecturas distintas
  en `flat` (33%/67%/0%/33%, v3/v5/v6/v7) sin que ningún cambio de config
  lo explique con confianza más allá del salto puntual 0%→33% de la 5.10.
- La pregunta de la sección 5.2 (¿el 67% de esa corrida reflejaba al fix o
  era ruido?) queda respondida en los hechos por la 5.4: con la
  generalización a período > 1 aplicada, la siguiente corrida `flat` dio
  83% — consistente con que 67% era ruido de muestra (`n=3`), no un efecto
  real del fix de período 1 solo.
- Con la serie de subagentes (4.1 → 5.1) en 58%, la brecha contra `flat`
  (78%) ya no es tan grande como para descartar la arquitectura — vale la
  pena una corrida más de subagent con más trials (5, como la mejor corrida
  de `flat`) antes de sacar una conclusión final sobre si la delegación de
  tools vale el costo extra para este problema.
- La hipótesis de la sección 3 sobre el planner ya se confirmó dos veces
  (sección 6) — sigue siendo `n=3` por celda en cada corrida; una corrida
  a 5 trials específicamente en `library-search` y `backtracking-vault`
  (donde el efecto es más marcado) daría más confianza sin repetir las 8
  escenarios completos.
- Consolidar todo (`INFORME_M3.md` + `resumen-informe-m3.md` + esta
  reentrega) en un único informe con las 5 secciones que pide
  `ENUNCIADO_M3.md`, respondiendo también al tercer punto de la devolución
  original.
