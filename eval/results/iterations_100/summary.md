## Resultados — `iterations_100`

config: `{'max_iterations': 100}` · módulo: `student_framework` · 8 escenarios x 3 trials · 1224.9s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 4.7 / 3 | 0.65 | 4.7 | 9406/301 | 5.5 |
| color-locks | medium | 3 | 33% | 43.7 / 11 | 0.91 | 26.0 | 163684/2929 | 49.8 |
| library-search | hard | 3 | 67% | 46.0 / 7 | 0.27 | 18.5 | 242608/4336 | 66.2 |
| extreme-archive | extreme | 3 | 33% | 9.3 / 4 | 1.17 | 23.0 | 79878/1306 | 17.1 |
| apartment-keys | medium | 3 | 67% | 40.7 / 7 | 0.45 | 11.0 | 141292/2022 | 40.9 |
| office-sequence | hard | 3 | 33% | 46.7 / 13 | 0.58 | 19.0 | 168819/2128 | 55.7 |
| vault-combination | extreme | 3 | 33% | 95.3 / 21 | 0.35 | 29.0 | 293072/4430 | 90.8 |
| backtracking-vault | extreme | 3 | 33% | 78.0 / 18 | 0.30 | 25.0 | 299990/4277 | 82.0 |
| **TOTAL** | — | 24 | **50%** | — | — | — | — | — |

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | 1 | 2 | 1 | — | 1 | 1 | 1 | 7 |
| max_iterations_agotado | 1 | 2 | 1 | — | 1 | 1 | 2 | 8 |
| perdida_de_mapa_multi_sala | 1 | 1 | — | — | — | — | 2 | 4 |
| se_detuvo_sin_lograr_la_meta | — | — | 1 | 2 | — | 1 | — | 4 |
