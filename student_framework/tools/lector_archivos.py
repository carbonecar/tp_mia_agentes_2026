"""
Lector de archivos con acceso acotado al directorio archivos del path local.

M2: los errores de sandbox (ruta vacía/absoluta/con `..`/fuera del directorio),
archivo inexistente y ruta-es-directorio son recuperables — se devuelven como
`ValueError` con un mensaje accionable (qué regla se violó, cómo debe verse una
ruta válida, y en los casos de archivo inexistente o directorio, qué archivos
hay disponibles) para que el LLM pueda corregir la ruta y reintentar.
"""

from typing import Annotated
from pydantic import Field
from mia_agents.types import ToolSchema
import os

_SANDBOX_DIR_NAME = "archivos"


def _sandbox_dir() -> str:
    return os.path.abspath(_SANDBOX_DIR_NAME)


def _listar_directorio(path_dir: str) -> str:
    try:
        entradas = sorted(os.listdir(path_dir))
    except OSError:
        return "(no se pudo listar el directorio)"
    if not entradas:
        return "(el directorio está vacío)"
    return ", ".join(entradas)


def _resolver_ruta_segura(ruta: str) -> str:
    """Valida `ruta` contra el sandbox `archivos/` y devuelve la ruta absoluta.

    Levanta `ValueError` con un mensaje accionable si la ruta viola alguna regla.
    """
    if not ruta or not ruta.strip():
        raise ValueError(
            "La ruta no puede estar vacía. Pasá un nombre de archivo relativo al "
            "directorio 'archivos' (ej: 'notas.txt' o 'subcarpeta/datos.txt')."
        )
    if os.path.isabs(ruta):
        raise ValueError(
            f"La ruta '{ruta}' es absoluta y no está permitida. Usá una ruta "
            "relativa al directorio 'archivos', sin '/' inicial (ej: 'notas.txt')."
        )
    if ".." in ruta.replace("\\", "/").split("/"):
        raise ValueError(
            f"La ruta '{ruta}' contiene '..' y no está permitida (no se puede "
            "salir del directorio 'archivos'). Usá una ruta relativa dentro de "
            "ese directorio, ej: 'notas.txt' o 'subcarpeta/datos.txt'."
        )

    base = _sandbox_dir()
    candidata = os.path.abspath(os.path.join(base, ruta))
    if os.path.commonpath([base, candidata]) != base:
        raise ValueError(
            f"La ruta '{ruta}' escapa del directorio permitido 'archivos'. Usá "
            "una ruta relativa dentro de ese directorio, ej: 'notas.txt'."
        )
    return candidata


def leer_archivo(
    ruta: Annotated[str, Field(description="Nombre del archivo a leer, relativo al directorio 'archivos'.")],
) -> str:
    """Lee el contenido de un archivo de texto y devuelve su contenido como una cadena.

    Args:
        ruta (str): ruta relativa al directorio 'archivos'. No puede ser absoluta,
            ni contener '..', ni escapar de ese directorio.

    Returns:
        str: El contenido del archivo.
    """
    ruta_absoluta = _resolver_ruta_segura(ruta)

    if os.path.isdir(ruta_absoluta):
        contenido_dir = _listar_directorio(ruta_absoluta)
        raise ValueError(
            f"'{ruta}' es un directorio, no un archivo. Elegí uno de sus "
            f"archivos: {contenido_dir}."
        )

    if not os.path.isfile(ruta_absoluta):
        directorio_padre = os.path.dirname(ruta_absoluta) or _sandbox_dir()
        if os.path.isdir(directorio_padre):
            disponibles = _listar_directorio(directorio_padre)
            raise ValueError(
                f"El archivo '{ruta}' no existe. Archivos disponibles en su "
                f"directorio: {disponibles}."
            )
        raise ValueError(
            f"El archivo '{ruta}' no existe y su directorio contenedor tampoco. "
            "Verificá la ruta e intentá con un archivo dentro de 'archivos'."
        )

    try:
        with open(ruta_absoluta, 'r', encoding='utf-8') as archivo:
            return archivo.read()
    except UnicodeDecodeError:
        raise ValueError(
            f"El archivo '{ruta}' no es texto UTF-8 válido; esta herramienta "
            "solo lee archivos de texto."
        ) from None


leer_archivo_schema = ToolSchema.from_callable(leer_archivo)
