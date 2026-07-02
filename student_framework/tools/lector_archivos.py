"""
Lector de archivos con acceso acotado al directorio archivos del path local
"""

from typing import Annotated
from pydantic import Field
from mia_agents.types import ToolSchema
import os

def leer_archivo(
    ruta: Annotated[str, Field(description="Nombre del archivo a leer en el directorio archivos.")],
) -> str:
    """Lee el contenido de un archivo de texto y devuelve su contenido como una cadena.

    Args:
        ruta (str): La ruta del archivo a leer.

    Returns:
        str: El contenido del archivo.
    """
    # Verificar si la ruta es absoluta
    if os.path.isabs(ruta):
        raise ValueError("La ruta NO debe ser absoluta.")
    ruta= os.path.join("archivos", ruta)
    # Verificar si el archivo existe
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"El archivo '{ruta}' no existe.")

    
    # Leer el contenido del archivo
    with open(ruta, 'r', encoding='utf-8') as archivo:
        contenido = archivo.read()

    return contenido


leer_archivo_schema = ToolSchema.from_callable(leer_archivo)
