## Resultados — `baseline_prompt`

config: `{'system_prompt': 'Sos un agente que resuelve escape rooms textuales. Recibis una situacion inicial y debes\nescapar (o cumplir el objetivo indicado) usando unicamente las herramientas disponibles:\n`look`, `examine`, `take`, `use`, y `go` (esta ultima solo si hay salidas entre salas).\n\nReglas del mundo:\n- Los objetos tienen un id interno (p. ej. "llave_oro") que debes usar tal cual en las\n  llamadas a herramientas, no el nombre en lenguaje natural.\n- Muchos objetos son contenedores: podes no ver su contenido hasta examinarlos. Si un\n  contenedor esta cerrado con llave, primero hay que abrirlo con use.\n- Algunos objetos estan ocultos dentro de otros (p. ej. una llave bajo una alfombra, o\n  dentro de un cofre). No vas a poder tomarlos hasta examinar el contenedor que los oculta.\n- Las cerraduras pueden requerir un unico item especifico, o varias piezas distintas que\n  hay que colocar una por una con use antes de que se abran del todo -- examine  hay que colocar una por una con use antes de que se abran del todo -- examine  hay que colocar una por una con use an\n  esta bloqueada por una puerta/reja sin abrir. Movete co  esta bloqueada por una puerta/reja sin abrir. Movete co  esta bloqueada por una puertra con look y examine antes de\n  actuar, y confirma el efecto de cada accion con el texto q  actuar, y co her  actuar, y confirma el efecto de cada accion con el texto q  actuar, y co her  actible  actuar, y confirma el efecto de cada accion con el textoe)   actuar, y confirma el efecto de cada accion con el texto q  actuar, y co her  actos.\n3. Toma (take) todo objeto tomable relevante en cuanto sea visible.\n44444444444444444444444444444444444444444444444444444444444444444444444444444444444444dos\n   probando la combinacion mas logica segun nombres/colores/descripciones.\n5. Si una accion falla (mensaje de error), no la repitas igual: reinterpreta la pista y\n   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   prje   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otra co   proba otranventes objetos ni acciones que no existan: si algo no aparece en look/examine, no\nexiste todavia. No declares el escenario resuelto en tu respuesta final hasta haber\nconfirmado el efecto (p. ej. "Se abre") en el resultado de una herramienta.'}` · módulo: `student_framework` · 8 escenarios x 3 trials · 213.1s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 7.7 / 3 | 0.42 | 6.7 | 22308/415 | 6.8 |
| color-locks | medium | 3 | 0% | 10.0 / 11 | 1.10 | — | 28822/747 | 9.4 |
| library-search | hard | 3 | 33% | 12.3 / 7 | 0.60 | 17.0 | 38928/786 | 10.5 |
| extreme-archive | extreme | 3 | 0% | 10.0 / 4 | 0.40 | — | 43630/795 | 10.0 |
| apartment-keys | medium | 3 | 0% | 10.0 / 7 | 0.70 | — | 27335/529 | 8.0 |
| office-sequence | hard | 3 | 0% | 10.3 / 13 | 1.26 | — | 27936/576 | 8.6 |
| vault-combination | extreme | 3 | 0% | 10.3 / 21 | 2.04 | — | 28431/614 | 8.8 |
| backtracking-vault | extreme | 3 | 0% | 10.3 / 18 | 1.75 | — | 28531/594 | 8.6 |
| **TOTAL** | — | 24 | **17%** | — | — | — | — | — |

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | color-locks | extreme-archive | library-search | office-sequence | vault-combination | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accion_repetida_fallida | — | 1 | 1 | — | — | — | — | 2 |
| desborde_de_contexto | — | — | — | 3 | — | — | — | 3 |
| max_iterations_agotado | 3 | 3 | 3 | 3 | 2 | 3 | 3 | 20 |
