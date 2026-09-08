"""Tool de solo-lectura que arma un mapa determinístico de navegación.

Motivación: `perdida_de_mapa_multi_sala` es el modo de fallo más
persistente de todo M3 (ver `INFORME_M3.md`) — el prompt le pide
explícitamente al agente "mantené una lista de salas visitadas" y no
alcanza, porque esa lista vive en la prosa del modelo, no en ningún lado
verificable. Esta tool convierte esa lista en datos: arma el mapa
directamente desde `World`, sin pasar por el LLM en ningún momento (mismo
espíritu que `_apply_ground_truth` en `explorer_subagent.py`, pero para
topología de salas en vez de inventario/cerraduras). Sin costo, sin
necesidad de caché — es barato recalcularla siempre.

Complementa a `look`/`examine`/`explorar_sala`, no las reemplaza: esta tool
no describe objetos, solo la estructura espacial ya conocida.

Qué cuenta como "ya conocido" (para no filtrarle al agente información que
no tiene realmente): `look()` ya revela *todas* las direcciones de salida
de la sala en la que estás parado (incluidas las bloqueadas, marcadas con
el nombre del gate), pero nunca revela a qué sala lleva una dirección
hasta que la cruzás. Por eso:

  - Las salas visitadas y el camino recorrido (con repeticiones, para que
    el backtracking quede explícito) salen de `world.event_log`
    (entradas `"enter:<sala>"`).
  - Las direcciones de salida de cada sala visitada son siempre seguras de
    mostrar (`room.exits`): son exactamente lo que `look` ya mostró apenas
    se entró a esa sala.
  - El *destino* de una dirección solo se muestra si esa transición
    específica ya ocurrió — se infiere cruzando pares consecutivos del
    camino recorrido contra las salidas de la sala de origen. Nunca se
    inventa ni se adelanta un destino no confirmado, aunque la sala de
    destino ya se conozca por otro camino.
"""

from __future__ import annotations

from typing import Callable

from mia_agents.types import ToolSchema
from mia_world.state import World


def consultar_mapa() -> str:
    """Devuelve el mapa de navegación conocido hasta ahora: salas visitadas,
    camino recorrido, y para cada sala sus salidas — con el destino solo si
    esa salida ya se cruzó, marcado como "destino sin confirmar" si no."""
    raise NotImplementedError("usar make_room_graph_tool(world)")


consultar_mapa_schema = ToolSchema.from_callable(consultar_mapa)


def _visited_path(world: World) -> list[str]:
    path = [event.split(":", 1)[1] for event in world.event_log if event.startswith("enter:")]
    return path or [world.current_room]


def _confirmed_edges(world: World, path: list[str]) -> dict[tuple[str, str], str]:
    """Direcciones ya cruzadas de verdad: `(sala_origen, direccion) -> sala_destino`.

    Se infiere de pares consecutivos del camino recorrido, cruzando contra
    las salidas ya visibles de la sala de origen — nunca asume una
    transición que no está registrada en `event_log`. Si más de una
    dirección de la sala de origen coincide con el mismo destino (caso
    borde, no esperado en este dataset), se registran todas: preferible
    mostrar la ambigüedad real a fingir certeza.
    """
    edges: dict[tuple[str, str], str] = {}
    for origin, dest in zip(path, path[1:]):
        room = world.rooms.get(origin)
        if room is None:
            continue
        for direction, target in room.exits.items():
            if target == dest:
                edges[(origin, direction)] = dest
    return edges


def _build_map_text(world: World) -> str:
    path = _visited_path(world)

    visited_order: list[str] = []
    for room_id in path:
        if room_id not in visited_order:
            visited_order.append(room_id)

    edges = _confirmed_edges(world, path)

    breadcrumb = " -> ".join(world.rooms[r].name for r in path if r in world.rooms)
    lines = [
        f"Mapa conocido ({len(visited_order)} sala(s) visitada(s)):",
        f"Camino recorrido: {breadcrumb}",
        "",
    ]

    for room_id in visited_order:
        room = world.rooms.get(room_id)
        if room is None:
            continue
        marker = " (sala actual)" if room_id == world.current_room else ""
        lines.append(f"- {room.name}{marker}")
        if not room.exits:
            lines.append("  (sin salidas)")
            continue
        for direction in sorted(room.exits):
            dest_id = edges.get((room_id, direction))
            if dest_id is not None:
                dest_name = world.rooms[dest_id].name if dest_id in world.rooms else dest_id
                lines.append(f"  - {direction} -> {dest_name} (visitada)")
                continue
            gate_id = room.locked_exits.get(direction)
            gate = world.items.get(gate_id) if gate_id else None
            if gate is not None:
                status = "abierta" if gate.open_state == "open" else "cerrada"
                lines.append(f"  - {direction}: bloqueada por {gate.name} ({status}), destino sin confirmar")
            else:
                lines.append(f"  - {direction}: destino sin confirmar")

    return "\n".join(lines)


def make_room_graph_tool(world: World) -> tuple[Callable[[], str], ToolSchema]:
    """Arma `consultar_mapa` enlazada a `world`. Sin LLM, sin costo, sin caché."""

    def consultar_mapa_impl() -> str:
        return _build_map_text(world)

    return consultar_mapa_impl, consultar_mapa_schema
