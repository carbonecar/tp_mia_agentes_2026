## Resultados — `iterations_100`

config: `{'max_iterations': 100}` · módulo: `student_framework` · 8 escenarios x 3 trials · 471.1s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.3 / 3 | 0.57 | 5.3 | 10686/325 | 5.4 |
| color-locks | medium | 3 | 0% | 26.0 / 11 | 0.42 | — | 77809/1742 | 25.9 |
| library-search | hard | 3 | 33% | 17.0 / 7 | 0.55 | 19.0 | 58570/1140 | 17.3 |
| extreme-archive | extreme | 3 | 67% | 24.3 / 4 | 0.16 | 24.0 | 222313/2297 | 34.9 |
| apartment-keys | medium | 3 | 100% | 12.3 / 7 | 0.57 | 12.3 | 28951/673 | 10.9 |
| office-sequence | hard | 3 | 0% | 20.7 / 13 | 0.73 | — | 54562/959 | 17.4 |
| vault-combination | extreme | 3 | 33% | 27.7 / 21 | 0.76 | 28.0 | 63644/1297 | 21.3 |
| backtracking-vault | extreme | 3 | 0% | 25.0 / 18 | 0.72 | — | 76474/1559 | 23.8 |
| **TOTAL** | — | 24 | **42%** | — | — | — | — | — |

### Modos de fallo

| Categoría | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | 3 | 3 | — | — | 1 | 2 | 9 |
| fallo_llm_no_transitorio | 3 | 3 | 1 | 1 | 2 | 2 | 12 |
| perdida_de_mapa_multi_sala | 3 | — | — | — | 2 | 2 | 7 |
| se_detuvo_sin_lograr_la_meta | — | — | — | 1 | 1 | — | 2 |
