## Resultados — `flat-default-prompt-t3-h100-i100`

config: `{'max_history_messages': 100, 'max_iterations': 100}` · agent_mode: `flat` · módulo: `student_framework` · 8 escenarios x 3 trials · 2017.0s total

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

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | 1 | 2 | — | — | — | 1 | 2 | 6 |
| desborde_de_contexto | — | — | — | 1 | — | — | — | 1 |
| max_iterations_agotado | 1 | 2 | — | 1 | — | 1 | 2 | 7 |
| perdida_de_mapa_multi_sala | 1 | — | — | — | — | — | 1 | 2 |
| se_detuvo_sin_lograr_la_meta | — | — | 2 | — | 1 | — | 1 | 4 |
