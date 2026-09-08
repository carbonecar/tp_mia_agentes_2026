"""Tool `explorar_sala`: delegación a un sub-agente 'explorador' (M3).

Experimento de framework (no de prompt/iteraciones): en vez de que el mismo
agente decida `look`/`examine`/`take`/`use`/`go` en un único loop
monolítico, se separan responsabilidades entre dos agentes:

- **Explorador**: solo tiene `look`/`examine` registradas. Investiga la
  sala actual a fondo y devuelve un resumen en texto.
- **Actor**: registra `take`/`use`/`go` más esta tool (`explorar_sala`) en
  vez de `look`/`examine` directas, y decide sus acciones a partir del
  resumen que le devuelve el explorador.

`make_explorer_tool` arma la tool que el actor registra; cada invocación
construye un `MyAgent` explorador *nuevo* (no acumula historial entre
llamadas) para que cada resumen describa el estado actual de la sala, no
una mezcla con exploraciones pasadas.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Callable

from pydantic import Field

from mia_agents.protocols import LLMClient
from mia_agents.types import ToolSchema
from mia_world.state import World

from student_framework.agent import MyAgent

EXPLORER_SYSTEM_PROMPT = (
    "Sos un sub-agente 'explorador' dentro de un escape-room simulado. Tu único "
    "trabajo es investigar a fondo la sala actual y el inventario; nunca tomás "
    "ni usás objetos ni te movés de sala (no tenés esas herramientas). Usá "
    "`look` primero, y después `examine` sobre cada objeto de interés que "
    "aparezca —incluidos los contenedores, para revelar su contenido— hasta "
    "agotar lo que hay para ver, sin repetir la misma llamada dos veces.\n\n"
    "Cuando termines, respondé **siempre en español** con el resumen en "
    "**exactamente** este formato, sin texto antes ni después, sin explicar tu "
    "razonamiento, sin etiquetas como '<thinking>', y sin repetir el resumen "
    "dos veces — la respuesta a otro agente que va a actuar con esto, no a una "
    "persona, así que tiene que ser corta y sin relleno:\n\n"
    "Sala: <nombre>\n"
    "Salidas: <dirección> -> <sala destino> (<abierta|bloqueada por X>); ... "
    "o 'ninguna' si no hay\n"
    "Objetos visibles: <id> (<abierto|cerrado|n/a>); ...\n"
    "Contenedores revelados: <id del contenedor>: <ids de lo que contiene>; ... "
    "o 'ninguno'\n"
    "Cerraduras: <id> requiere <ítem(s)>, faltan: <...>; ... o 'ninguna'\n"
    "Inventario: <ids>; o 'vacío'\n\n"
    "Completá cada línea con lo que encontraste, en ese orden, sin agregar "
    "secciones nuevas ni comentarios fuera de esas 6 líneas."
)

def _explorer_directive(foco: str | None) -> str:
    if foco:
        return (
            f"Enfocate específicamente en el objeto con id '{foco}': usá `examine` sobre él "
            "(y `look` primero solo si todavía no tenés contexto de la sala) para conocerlo "
            "en detalle — no hace falta que examines el resto de los objetos de la sala esta "
            "vez. Devolveme igual el resumen completo en el formato fijo de tus instrucciones, "
            f"con lo que encontraste sobre '{foco}' en la línea que le corresponda (`Objetos "
            "visibles:` o `Contenedores revelados:` si es un contenedor)."
        )
    return (
        "Explorá la sala actual y el inventario a fondo y devolveme el resumen "
        "descripto en tus instrucciones."
    )


def explorar_sala(
    foco: Annotated[
        str | None,
        Field(
            description=(
                "Opcional: id de un objeto puntual (de los que ya te mostró una exploración "
                "anterior) para que el explorador lo examine en detalle, en vez de barrer toda "
                "la sala de nuevo. Usalo cuando ya sabés qué objeto te interesa (p. ej. decidir "
                "cuál de varios libros es el correcto) — es más rápido y preciso que pedir una "
                "exploración general. Si se omite, explora la sala completa como siempre."
            )
        ),
    ] = None,
) -> str:
    """Delega en un sub-agente 'explorador' (con acceso a `look`/`examine`) que
    investiga la sala actual —incluido el contenido de los contenedores
    visibles— y devuelve un resumen en texto de lo que encontró: salidas,
    objetos con sus ids, contenedores y su contenido, e inventario. Sin
    `foco`, explora todo; con `foco`, se concentra en ese objeto puntual.
    Usala en vez de llamar `look`/`examine` vos mismo."""
    raise NotImplementedError("usar make_explorer_tool(...)")


explorar_sala_schema = ToolSchema.from_callable(explorar_sala)


def _state_signature(world: World) -> tuple[Any, ...]:
    """Fotografía barata de todo lo que un resumen de sala podría reportar
    distinto: sala actual, inventario, contenedores revelados, y estado/
    piezas colocadas de cada item con cerradura. Dos llamadas con la misma
    firma no pueden producir un resumen distinto — nada visible cambió.
    """
    items_state = tuple(
        sorted((item.id, item.open_state, tuple(item.inserted)) for item in world.items.values())
    )
    return (
        world.current_room,
        tuple(sorted(world.inventory)),
        tuple(sorted(world.revealed)),
        items_state,
    )


def _ground_truth_lines(world: World) -> dict[str, str]:
    """Calcula, directo desde `world` (sin pasar por ningún LLM), el texto
    correcto de las líneas `Inventario:` y `Cerraduras:` del formato fijo de
    `EXPLORER_SYSTEM_PROMPT`.

    Se limita a estas dos porque son datos discretos, 100% derivables de
    `world` sin ambigüedad, y son justo la clase de dato donde se encontró
    una alucinación real (`REENTREGA.md`, sección 4.6: el explorador
    reportaba una llave en el inventario que el actor nunca había tomado).
    Deliberadamente NO se toca `Salidas:` ni `Objetos visibles:`: la
    descripción de una sala (`room.description`, que sí ve el explorador
    vía `look`) suele nombrar la sala vecina de cada salida como parte del
    texto narrativo (ver `scenarios/*.json`), algo que reconstruir solo
    desde `room.exits` perdería — ahí el LLM aporta más de lo que el
    código puede derivar mecánicamente, así que se lo deja como está.
    """
    if world.inventory:
        inventario = ", ".join(
            f"{world.items[i].name} [id: {i}]" if i in world.items else i for i in world.inventory
        )
    else:
        inventario = "vacío"

    cerraduras_parts: list[str] = []
    for item in sorted(world.items.values(), key=lambda it: it.id):
        if item.locked is None or item.open_state == "open":
            continue
        required_items = item.locked.get("requires_items")
        if required_items:
            missing = [r for r in required_items if r not in item.inserted]
            missing_names = ", ".join(
                f"{world.items[m].name} [id: {m}]" if m in world.items else m for m in missing
            )
            cerraduras_parts.append(
                f"{item.name} [id: {item.id}] requiere {len(required_items)} piezas, faltan: {missing_names}"
            )
        else:
            required = item.locked.get("requires_item")
            req_label = f"{world.items[required].name} [id: {required}]" if required in world.items else required
            cerraduras_parts.append(f"{item.name} [id: {item.id}] requiere {req_label}")
    cerraduras = "; ".join(cerraduras_parts) if cerraduras_parts else "ninguna"

    return {"Inventario": inventario, "Cerraduras": cerraduras}


_GROUND_TRUTH_LINE_RE = {
    field: re.compile(rf"^\s*{field}\s*:.*$", re.IGNORECASE | re.MULTILINE)
    for field in ("Inventario", "Cerraduras")
}


def _apply_ground_truth(summary: str, world: World) -> str:
    """Reemplaza (o agrega, si el explorador se las salteó) las líneas
    `Inventario:`/`Cerraduras:` del resumen por el texto calculado en
    `_ground_truth_lines`, sin tocar el resto de lo que redactó el LLM.
    """
    truth = _ground_truth_lines(world)
    result = summary
    for field, pattern in _GROUND_TRUTH_LINE_RE.items():
        replacement = f"{field}: {truth[field]}"
        if pattern.search(result):
            result = pattern.sub(replacement, result, count=1)
        else:
            result = result.rstrip("\n") + f"\n{replacement}"
    return result


def make_explorer_tool(
    llm_client: LLMClient,
    look_pair: tuple[Callable[..., str], ToolSchema],
    examine_pair: tuple[Callable[..., str], ToolSchema],
    world: World,
    *,
    max_iterations: int = 6,
    max_calls: int | None = 25,
    cost_sink: dict[str, Any] | None = None,
) -> tuple[Callable[..., str], ToolSchema]:
    """Arma `(callable, schema)` de `explorar_sala` para `agent.register_tool`.

    `look_pair`/`examine_pair` son los pares `(callable, ToolSchema)` que
    devuelve `mia_world.tools.make_world_tools(world)` para esos dos verbos
    — ya enlazados al `World` de la corrida, así el explorador ve el mismo
    estado que el actor. `world` (la misma instancia) se usa acá solo para
    calcular `_state_signature` antes/después de correr al explorador.

    **Caché por firma de estado** (no un tope ciego): si el mundo no cambió
    desde la última exploración real (mismo `_state_signature` — misma sala,
    inventario, contenedores revelados y estado de cerraduras), se devuelve
    el resumen ya obtenido sin correr un explorador nuevo. Es distinto de
    simplemente negarse a explorar: el actor sigue recibiendo información
    real y actualizada en cada llamada, solo que gratis cuando ya se sabía.
    En cuanto el actor hace algo que cambia el mundo (`take`/`use`/`go`
    exitosos), la siguiente `explorar_sala` vuelve a correr el explorador de
    verdad. Primera versión de este módulo usaba un tope duro de invocaciones
    (`max_calls=6` sin caché): frenaba el costo pero dejaba al actor sin
    forma de pedir info nueva después de agotarlo — colapsó el éxito a 12%
    en la corrida real (`eval/results/subagent-t3-h100-i100/`, ver
    `REENTREGA.md`) porque escenarios con varias salas/objetos necesitan
    re-explorar bastante más de 6 veces por diseño.

    `max_iterations` acota cada corrida *real* del explorador (6: en la
    misma corrida real, 4 resultó insuficiente — el explorador agotaba sus
    propios pasos sin llegar a sintetizar un resumen en el 63% de sus
    invocaciones reales).

    `max_calls` sigue existiendo como último circuito de seguridad —cuenta
    solo corridas reales del explorador, no los aciertos de caché— para
    acotar el peor caso absoluto si el mundo cambia en cada paso sin
    converger nunca (`max_calls × max_iterations` llamadas extra como
    tope duro).

    **`foco` (id de un objeto puntual)**: sin `foco`, el explorador barre
    toda la sala; con `foco`, se concentra en examinar ese objeto y nada
    más. Encontrado en la práctica (`REENTREGA.md`, sección 5.7): sin esta
    opción, el actor solo podía pedir "explorá todo de nuevo" para
    averiguar más sobre un objeto puntual entre varios (p. ej. decidir cuál
    de 8 libros es el correcto en `library-search`), lo que lo empujaba a
    probar `take` a ciegas sobre cada uno en vez de pedir una lectura más
    profunda de uno solo. La caché (`cached_key`) se indexa por
    `(estado, foco)`, no solo por estado: una exploración general y una
    enfocada en un objeto son pedidos distintos aunque el mundo no haya
    cambiado, y no deben compartir resultado cacheado.

    `cost_sink`, si se pasa, acumula `calls`/`input_tokens`/`output_tokens`
    de cada corrida real del explorador (los aciertos de caché no cuentan,
    no arrancan ningún `MyAgent` nuevo). `mia_agents.types.AgentResult`
    documenta que "sub-agentes invocados por herramientas NO se
    contabilizan" en el resultado del agente que los invoca — así que sin
    este sink el costo real del modo subagente quedaría invisible para
    `eval/metrics.py`.

    **Verdad determinística en vez de confiar en el LLM**: las líneas
    `Inventario:`/`Cerraduras:` del resumen del explorador se descartan y se
    recalculan directo desde `world` (`_apply_ground_truth`) antes de
    devolverlas al actor — nunca lo que escribió el LLM. Se encontró en la
    práctica que el explorador puede "alucinar" estos campos por completado
    de plantilla (reportar un ítem en el inventario que el actor nunca tomó,
    ver `REENTREGA.md` sección 4.6); como ambos son datos discretos 100%
    derivables sin ambigüedad, no hace falta confiar en que el LLM los
    reporte bien. `Salidas:`/`Objetos visibles:`/`Sala:` siguen siendo
    enteramente del explorador porque sí requieren síntesis (la descripción
    narrativa de una sala puede nombrar la sala vecina de una salida, algo
    que el código no puede reconstruir solo desde `room.exits`).
    """
    real_calls_so_far = 0
    cached_key: tuple[Any, ...] | None = None
    cached_summary: str | None = None

    def explorar_sala_impl(foco: str | None = None) -> str:
        nonlocal real_calls_so_far, cached_key, cached_summary

        # La caché se indexa por (estado, foco): una exploración general y una
        # enfocada en un objeto puntual son pedidos distintos aunque el mundo
        # no haya cambiado — no deben compartir el resultado cacheado.
        key = (_state_signature(world), foco)
        if cached_summary is not None and key == cached_key:
            return (
                "(nada cambió en la sala/inventario desde la última exploración — "
                "mismo resumen de antes, no hace falta volver a explorar)\n" + cached_summary
            )

        if max_calls is not None and real_calls_so_far >= max_calls:
            return (
                f"Ya se exploró la sala {real_calls_so_far} veces en este intento sin converger. "
                "Dejá de re-explorar y actuá con la información que ya tenés (take/use/go), o si "
                "ya cumpliste el objetivo, respondé con tu conclusión final sin llamar a más "
                "herramientas."
            )

        explorer = MyAgent(
            llm_client=llm_client,
            system_prompt=EXPLORER_SYSTEM_PROMPT,
            max_iterations=max_iterations,
        )
        explorer.register_tool(*look_pair)
        explorer.register_tool(*examine_pair)
        result = explorer.run(_explorer_directive(foco))
        real_calls_so_far += 1

        if cost_sink is not None:
            cost_sink["calls"] = cost_sink.get("calls", 0) + 1
            if result.input_tokens is not None:
                cost_sink["input_tokens"] = cost_sink.get("input_tokens", 0) + result.input_tokens
            if result.output_tokens is not None:
                cost_sink["output_tokens"] = cost_sink.get("output_tokens", 0) + result.output_tokens

        if result.answer:
            summary = _apply_ground_truth(result.answer, world)
            cached_key = key
            cached_summary = summary
            return summary
        # No se cachea: un resumen vacío es un fallo del explorador (agotó su
        # propio presupuesto), no información real sobre la sala. Cachearlo
        # dejaría al actor sin poder obtener nunca un resumen útil de este
        # estado — mejor permitir que un reintento futuro (mismo estado)
        # vuelva a correr el explorador de verdad. Igual devolvemos lo único
        # que sabemos con certeza (inventario/cerraduras, calculado sin LLM)
        # en vez de dejar al actor con cero información.
        truth = _ground_truth_lines(world)
        return (
            "(el explorador no devolvió ningún resumen; puede haber agotado sus pasos. "
            "Esto sí es seguro:)\n"
            f"Inventario: {truth['Inventario']}\n"
            f"Cerraduras: {truth['Cerraduras']}"
        )

    return explorar_sala_impl, explorar_sala_schema
