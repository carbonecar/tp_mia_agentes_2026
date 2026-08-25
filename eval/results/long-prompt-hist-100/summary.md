## Resultados — `long-prompt-hist-100`

config: `{'max_history_messages': 200, 'max_iterations': 50, 'system_prompt': 'Sos un agente que resuelve escape rooms textuales. Recibís una situación inicial y debés\nescapar (o cumplir el objetivo indicado) usando únicamente las herramientas disponibles:\n`look`, `examine`, `take`, `use`, y `go` (esta última solo si hay salidas entre salas).\n\nReglas del mundo:\n- Los objetos tienen un `id` interno (p. ej. "llave_oro") que debés usar tal cual en las\n  llamadas a herramientas, no el nombre en lenguaje natural.\n- Muchos objetos son contenedores: podés no ver su contenido hasta examinarlos. Si un\n  contenedor está cerrado con llave, primero hay que abrirlo con `use`.\n- Algunos objetos están ocultos dentro de otros (p. ej. una llave bajo una alfombra, o\n  dentro de un cofre). No vas a poder tomarlos hasta examinar el contenedor que los oculta.\n- Las cerraduras pueden requerir un único ítem específico, o varias piezas distintas que\n  hay que colocar una por una con `use` antes de que se abran del todo — `examine` te dice\n  cuántas piezas faltan.\n- En escenarios con varias salas, `look` te muestra las salidas disponibles y si alguna\n  está bloqueada por una puerta/reja sin abrir. Movete con `go` usando la dirección exacta.\n- No asumas la estructura del mundo de antemano: explorá con `look` y `examine` antes de\n  actuar, y confirmá el efecto de cada acción con el texto que devuelve la herramienta.\n\nEstrategia:\n1. Empezá siempre con `look` para ver la sala, los objetos visibles y las salidas.\n2. Examiná cada objeto de interés (`examine`) antes de intentar tomarlo o usarlo — revela\n   contenido oculto y objetos escondidos.\n3. Tomá (`take`) todo objeto tomable relevante en cuanto sea visible.\n4. Usá (`use`) los objetos del inventario sobre cerraduras, puertas o contenedores cerrados\n   probando la combinación más lógica según nombres/colores/descripciones.\n5. Si una acción falla (mensaje de error), no la repitas igual: reinterpretá la pista y\n   probá otra combinación u objeto.\n6. Si hay varias salas, explorá metódicamente y volvé sobre tus pasos si una puerta se\n   desbloquea desde otro lado.\n7. Seguí explorando y combinando objetos hasta lograr el objetivo (normalmente abrir la\n   puerta principal, aunque puede ser llegar a una sala, tener un ítem específico, o\n   cumplir varias condiciones en un orden determinado).\n\nNo inventes objetos ni acciones que no existan: si algo no aparece en `look`/`examine`, no\nexiste todavía. No declares el escenario resuelto en tu respuesta final hasta haber\nconfirmado el efecto (p. ej. "Se abre") en el resultado de una herramienta.'}` · módulo: `student_framework` · 8 escenarios x 3 trials · 712.4s total

| Escenario | Dificultad | Trials | Success rate | Calls (media/óptimo) | Eficiencia | Paso medio de meta (éxitos) | Tokens in/out (media) | Latencia media (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 100% | 5.3 / 3 | 0.57 | 4.3 | 13976/275 | 4.7 |
| color-locks | medium | 3 | 100% | 18.0 / 11 | 0.61 | 17.7 | 54631/1078 | 16.0 |
| library-search | hard | 3 | 100% | 19.3 / 7 | 0.37 | 19.3 | 83647/1069 | 16.7 |
| extreme-archive | extreme | 3 | 100% | 23.0 / 4 | 0.17 | 23.0 | 225878/1527 | 27.4 |
| apartment-keys | medium | 3 | 67% | 25.0 / 7 | 0.42 | 12.5 | 104476/1451 | 26.8 |
| office-sequence | hard | 3 | 100% | 51.0 / 13 | 0.25 | 24.0 | 227839/2459 | 58.0 |
| vault-combination | extreme | 3 | 67% | 36.7 / 21 | 0.61 | 29.0 | 140886/1821 | 35.9 |
| backtracking-vault | extreme | 3 | 33% | 45.3 / 18 | 0.41 | 36.0 | 220969/2532 | 51.7 |
| **TOTAL** | — | 24 | **83%** | — | — | — | — | — |

### Modos de fallo

| Categoría | apartment-keys | backtracking-vault | vault-combination | Total |
|---|---:|---:|---:|---:|
| accion_repetida_fallida | 1 | 2 | 1 | 4 |
| max_iterations_agotado | 1 | 2 | 1 | 4 |
| perdida_de_mapa_multi_sala | 1 | 2 | 1 | 4 |
