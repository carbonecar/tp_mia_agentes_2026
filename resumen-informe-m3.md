# Resumen de corridas — M3

Consolida los `summary.md`/`summary.json` de `eval/results/*/` en una sola
línea de tiempo: qué cambió en cada corrida y cómo se movió el resultado,
caso por caso. No reemplaza a `INFORME_M3.md` (que documenta la
metodología y el bug de la ventana deslizante en detalle) — es el
seguimiento cronológico de todas las corridas hechas hasta ahora, incluidas
las de prompting e historial que `INFORME_M3.md` todavía marca como
pendientes.

Todas las corridas usan `--scenarios all --trials 3` (8 escenarios x 3
trials = 24 casos), salvo `smock`, que es un smoke test de 1 caso y se
reporta aparte.

## 1. Línea de tiempo de corridas

| # | Corrida (`--label`) | Cambio respecto a la anterior | Éxito global | Eficiencia media¹ | Tokens in/out (media) | Latencia media |
|---|---|---|---:|---:|---:|---:|
| 1 | `baseline` | Config por defecto: `system_prompt="Eres un asistente útil."`, `max_iterations=10`, `max_history_messages=50`. | 17% (4/24) | 1.02 | 22206/641 | 9.1s |
| 2 | `iterations_100-buggy` | `max_iterations: 10→100`. Corrida contra una versión del agente con un bug pendiente en la ventana deslizante de historial (mensajes `tool` huérfanos → `fallo_llm_no_transitorio` en Bedrock). | 42% (10/24) | 0.56 | 74126/1249 | 19.6s |
| 3 | `iterations_100` | Mismo `max_iterations: 100`, pero con el bug de la ventana deslizante corregido (ver `INFORME_M3.md` §4). `fallo_llm_no_transitorio` pasa de 12 a 0 casos. | 50% (12/24) | 0.58 | 174844/2716 | 51.0s |
| 4 | `baseline-prompt` | Primer prompt custom: pide descomponer el objetivo en sub-metas antes de actuar. `max_iterations`/`max_history_messages` vuelven al default (10/50). | 12% (3/24) | 1.07 | 23028/704 | 9.4s |
| 5 | `baseline_prompt` | Segundo prompt custom, más largo y explícito (ids de objetos, contenedores ocultos, cerraduras multi-pieza, salidas bloqueadas). **El archivo quedó corrompido al guardarlo** — tiene bloques de texto duplicados/repetidos (ver nota en §3). Mismo default de iteraciones/historial. | 17% (4/24) | 1.03 | 30740/632 | 8.8s |
| 6 | `long-prompt-hist-200` | Mismo prompt largo, esta vez limpio (`prompts/baseline_prompt.txt` reescrito sin corrupción) + `max_history_messages: 50→200`. `max_iterations` queda en el default (10). | 12% (3/24) | 1.05 | 29072/589 | 8.4s |
| 7 | `long-prompt-hist-100`² | Mismo prompt + `max_history_messages=200` **y** `max_iterations: 10→50`. | **83% (20/24)** | 0.43 | 134038/1527 | 29.6s |
| 8 | `long-prompt-hist-100-iterations-50` | Mismo prompt + `max_iterations=50`, pero `max_history_messages: 200→100`. | 75% (18/24) | 0.41 | 165518/1776 | 36.5s |
| 9 | `long-prompt-hist-100-iterations-100` | Mismo prompt + `max_history_messages=100` (igual que #8) y `max_iterations: 50→100`. | 75% (18/24) | 0.36 | 312178/2707 | 63.5s |

¹ Eficiencia = llamadas-a-tools reales / llamadas óptimas; **más bajo es mejor** (1.0 = tan eficiente como el óptimo, >1.0 = usó de más, <1.0 mezcla trials exitosos rápidos con trials que agotaron el presupuesto sin llegar — hay que leerla junto al éxito global, no sola).

² **Nota de nomenclatura:** la carpeta `long-prompt-hist-100` no usó `max_history_messages=100` sino **200** (`long-prompt-hist-200` fue el que se corrió sin subir `max_iterations`, y luego se reutilizó el mismo valor de historial subiendo iteraciones, pero el label no se renombró). El nombre real de la variable independiente en cada fila es el que aparece en la columna "Cambio", tomado del `config` de cada `summary.json`, no del label de la carpeta.

**Fuera de esta comparación:** `smock` es un smoke test de `max_iterations=100` sobre 1 solo caso (no 24) — no es comparable con las demás filas, solo confirma que el pipeline corre de punta a punta.

## 2. Progreso por caso (escenario)

Tasa de éxito (%) por escenario en cada corrida, mismo orden que la tabla anterior:

| Escenario | Dificultad | #1 baseline | #2 iter100-buggy | #3 iter100 | #4 baseline-prompt | #5 baseline_prompt | #6 hist200 | #7 hist200+iter50 | #8 hist100+iter50 | #9 hist100+iter100 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| color-locks | medium | 0% | 0% | 33% | 0% | 0% | 0% | **100%** | **100%** | **100%** |
| library-search | hard | 33% | 33% | 67% | 0% | 33% | 0% | **100%** | 33% | 33% |
| extreme-archive | extreme | 0% | 67% | 33% | 0% | 0% | 0% | **100%** | **100%** | **100%** |
| apartment-keys | medium | 0% | **100%** | 67% | 0% | 0% | 0% | 67% | 67% | **100%** |
| office-sequence | hard | 0% | 0% | 33% | 0% | 0% | 0% | **100%** | **100%** | **100%** |
| vault-combination | extreme | 0% | 33% | 33% | 0% | 0% | 0% | 67% | 33% | 33% |
| backtracking-vault | extreme | 0% | 0% | 33% | 0% | 0% | 0% | 33% | 67% | 33% |
| **TOTAL** | — | **17%** | **42%** | **50%** | **12%** | **17%** | **12%** | **83%** | **75%** | **75%** |

### Lectura por caso

- **study-with-key** (fácil): resuelto al 100% en las 9 corridas, sin excepción. No aporta señal — está saturado desde `baseline`.
- **color-locks** y **office-sequence**: patrón idéntico — 0% en todas las corridas hasta que se combinó prompt largo + `max_iterations≥50`, momento en el que saltan a 100% y se mantienen ahí en las tres corridas siguientes. Ninguno de los dos mejora con *solo* más iteraciones (#2, #3) ni con *solo* mejor prompt sin más presupuesto (#4-#6): necesitan ambos cambios juntos.
- **extreme-archive**: diseñado para desbordar el contexto de modelos chicos (ver `INFORME_M3.md`). Se mantiene en 0% mientras `max_iterations=10`, sin importar el prompt (#1, #4-#6). Con `max_iterations=100` sube a 67% incluso con el bug de historial activo (#2), lo que sugiere que el cuello de botella real es presupuesto de pasos, no el prompt. Se estabiliza en 100% en las tres corridas con prompt largo + historial ampliado (#7-#9).
- **apartment-keys**: el único caso con un resultado *mejor* bajo el bug de historial (#2, 100%) que corregido con el mismo `max_iterations` (#3, 67%) — posible ruido de muestra (3 trials) más que una regresión real. Es también el escenario que motivó la categoría `perdida_de_mapa_multi_sala` (ver conversación previa): sigue sin superar 67% en #7-#8 pese al prompt largo, y solo llega a 100% en #9 (más iteraciones todavía).
- **library-search**: el más inestable de todos — oscila entre 0% y 100% sin una tendencia clara según el cambio aplicado (33→33→67→0→33→0→**100**→33→33). El pico de 100% en #7 no se repite en #8/#9 con configuraciones muy similares, lo que apunta a variancia entre trials más que a una mejora estable.
- **vault-combination** y **backtracking-vault** (los dos "extreme" restantes): son el techo de esta serie de experimentos — ninguna combinación probada los lleva por encima de 67%, y la mayoría de las corridas los deja en 33%. Son los candidatos más claros para seguir iterando.

## 3. Observaciones sobre la ejecución de los experimentos

- **`baseline_prompt` (#5) se corrió con un archivo corrompido.** El `system_prompt` guardado en `prompts/baseline_prompt.txt` en ese momento tenía fragmentos de texto duplicados y una línea de `4444...` (visible en el `config` de `eval/results/baseline_prompt/summary.json`). El resultado (17%) es indistinguible del baseline sin prompt custom (también 17%), así que **no es evidencia de que ese prompt no ayude** — es evidencia de que el archivo que se usó no era el prompt pensado. La corrida limpia equivalente es `long-prompt-hist-200` (#6), que si aísla el prompt (sin tocar iteraciones) y da 12%, ligeramente peor que el baseline sin prompt.
- **El presupuesto de pasos (`max_iterations`) domina sobre el prompt.** Ninguna corrida con `max_iterations=10` (#1, #4, #5, #6) supera 17% de éxito global, sin importar qué tan detallado sea el prompt. El salto grande ocurre siempre que `max_iterations` sube a 50+ (#7, #8, #9: 75-83%). El prompt largo sí importa, pero solo *una vez* que hay presupuesto suficiente para actuar según lo que pide.
- **Más presupuesto no es gratis ni monotónicamente mejor.** #7→#9 no mejora el éxito global (83%→75%→75%) pero sí dispara el costo: tokens de entrada promedio pasan de 134k a 312k y la latencia media de 30s a 63s. `library-search` en #9 llega a consumir 676k tokens de entrada en un solo trial. Esto confirma lo discutido antes: el techo actual no es de presupuesto sino de que el agente entra en ciclos (`perdida_de_mapa_multi_sala`, `accion_repetida_fallida`) que más iteraciones simplemente alargan en vez de resolver.
- **Los modos de fallo migran con el presupuesto.** En las corridas con `max_iterations=10` (#1, #4-#6) casi todos los fallos son `max_iterations_agotado` (20-21 de 24 casos) — el agente ni siquiera llega a intentar una estrategia completa. Con `max_iterations≥50` (#7-#9) esa categoría casi desaparece y el fallo dominante pasa a ser `perdida_de_mapa_multi_sala` y `accion_repetida_fallida` (3-4 casos cada una) — el agente ya tiene margen para explorar, pero entra en bucles en vez de converger. Es el mismo diagnóstico de la sección anterior de esta conversación.

## 4. Mejor corrida hasta ahora

`long-prompt-hist-100` (#7): prompt largo + `max_history_messages=200` + `max_iterations=50` → **83% de éxito global**, resolviendo 6 de 8 escenarios al 100%. Los dos que quedan por debajo son `apartment-keys` (67%) y `backtracking-vault` (33%) — ambos con presencia de `perdida_de_mapa_multi_sala` en sus fallos.

## 5. Pendientes / próximos pasos

No implementados en esta ronda (ver discusión previa en esta conversación para el detalle de cada uno):

1. Detección de ciclos/repetición dentro del propio loop de `MyAgent.run`, para cortar el patrón `perdida_de_mapa_multi_sala` sin depender de más presupuesto de iteraciones.
2. Revisar la heurística de `perdida_de_mapa_multi_sala` en `eval/failure_modes.py` para que mida progreso real (vía `event_log`) en vez de volumen de `go`, y así distinguir backtracking legítimo (`backtracking-vault`) de extravío real (`apartment-keys`).
3. Repetir `baseline_prompt` (#5) con el archivo de prompt corregido, para tener una comparación limpia de "prompt largo, sin cambios de presupuesto" contra el baseline.
4. Foco específico en `vault-combination` y `backtracking-vault`, que no superan 67% en ninguna combinación probada.
