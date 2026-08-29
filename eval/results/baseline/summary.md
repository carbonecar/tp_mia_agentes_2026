## Resultados — `baseline`

config: `(default)` · módulo: `student_framework` · 8 escenarios x 3 trials · 218.4s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.3 / 3 | 0.57 | 5.3 | 10693/332 | 5.3 |
| color-locks | medium | 3 | 0% | 10.0 / 11 | 1.10 | — | 21567/730 | 10.2 |
| library-search | hard | 3 | 33% | 12.3 / 7 | 0.60 | 17.0 | 30269/844 | 11.0 |
| extreme-archive | extreme | 3 | 0% | 10.0 / 4 | 0.40 | — | 31897/890 | 11.3 |
| apartment-keys | medium | 3 | 0% | 10.0 / 7 | 0.70 | — | 20297/563 | 8.5 |
| office-sequence | hard | 3 | 0% | 10.3 / 13 | 1.26 | — | 20354/500 | 8.1 |
| vault-combination | extreme | 3 | 0% | 13.3 / 21 | 1.70 | — | 22069/730 | 9.6 |
| backtracking-vault | extreme | 3 | 0% | 10.0 / 18 | 1.80 | — | 20498/543 | 8.5 |
| **TOTAL** | — | 24 | **17%** | — | — | — | — | — |

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | — | 1 | 1 | — | — | — | 2 | 4 |
| desborde_de_contexto | — | — | — | 3 | — | — | — | 3 |
| max_iterations_agotado | 3 | 3 | 3 | 3 | 2 | 3 | 3 | 20 |
| perdida_de_mapa_multi_sala | — | 2 | — | — | — | — | 1 | 3 |
