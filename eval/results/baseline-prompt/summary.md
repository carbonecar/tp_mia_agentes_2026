## Resultados — `baseline-prompt`

config: `{'system_prompt': 'Sos un agente que resuelve puzzles tipo escape-room explorando una sala con herramientas (look/examine/take/use/go). Antes de actuar, descomponé el objetivo en una lista corta de sub-metas ordenadas y perseguilas una por una en ese orden; no actúes de forma puramente reactiva paso a paso.'}` · módulo: `student_framework` · 8 escenarios x 3 trials · 226.3s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 4.7 / 3 | 0.67 | 4.7 | 9842/295 | 4.7 |
| color-locks | medium | 3 | 0% | 10.0 / 11 | 1.10 | — | 22350/745 | 9.8 |
| library-search | hard | 3 | 0% | 10.0 / 7 | 0.70 | — | 27880/844 | 10.5 |
| extreme-archive | extreme | 3 | 0% | 10.0 / 4 | 0.40 | — | 36168/1056 | 12.1 |
| apartment-keys | medium | 3 | 0% | 10.0 / 7 | 0.70 | — | 21228/588 | 9.4 |
| office-sequence | hard | 3 | 0% | 10.0 / 13 | 1.30 | — | 21272/544 | 8.4 |
| vault-combination | extreme | 3 | 0% | 11.0 / 21 | 1.91 | — | 22527/717 | 9.7 |
| backtracking-vault | extreme | 3 | 0% | 10.0 / 18 | 1.80 | — | 22956/845 | 10.5 |
| **TOTAL** | — | 24 | **12%** | — | — | — | — | — |

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | 1 | 1 | — | — | — | — | — | 2 |
| desborde_de_contexto | — | — | — | 3 | — | — | — | 3 |
| max_iterations_agotado | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 21 |
| perdida_de_mapa_multi_sala | — | 1 | — | — | — | — | — | 1 |
