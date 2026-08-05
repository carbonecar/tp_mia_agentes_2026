"""
Calculadora simple que permite realizar operaciones basicas como suma, resta, division y
multiplicacion con solo dos parámetros.

M2: los errores de argumentos inválidos, operador no soportado y división/módulo
por cero son recuperables — se devuelven como `ValueError` con un mensaje
accionable (qué parámetro falló, qué valor recibió, por qué no es válido) para
que el LLM pueda corregir los argumentos y reintentar.
"""

from typing import Annotated
from pydantic import Field
from mia_agents.types import ToolSchema

_OPERACIONES_VALIDAS = ("suma", "resta", "multiplicacion", "division")


def _a_numero(valor: object, nombre_parametro: str) -> float:
    """Convierte `valor` a `float` o levanta un `ValueError` accionable."""
    if isinstance(valor, bool):
        raise ValueError(
            f"El parámetro '{nombre_parametro}' recibió un booleano ({valor!r}); "
            "se espera un número (ej: 3 o 3.5)."
        )
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(
            f"El parámetro '{nombre_parametro}' recibió {valor!r} "
            f"({type(valor).__name__}), que no es un número válido. "
            "Volvé a invocar la herramienta con un valor numérico, ej: 3 o 3.5."
        ) from None


def simple_calc(operacion: Annotated[str,Field(description="operador matematico a aplicar entre los operandos")],
            operando1:Annotated[float,Field(description="primer operando")],
            operando2:Annotated[float,Field(description="segundo operando")])->float:

    #En teoria es un antipatrón porque deberia tener una funcion por operacion
    """Calcula el resultado de una operación matemática básica entre dos operandos.

    Args:
        operacion (str): La operación a realizar. Puede ser 'suma', 'resta', 'multiplicacion' o 'division'.
        operando1 (float): El primer operando.
        operando2 (float): El segundo operando.

    Returns:
        float: El resultado de la operación.
    """
    op1 = _a_numero(operando1, "operando1")
    op2 = _a_numero(operando2, "operando2")

    if operacion not in _OPERACIONES_VALIDAS:
        raise ValueError(
            f"Operador '{operacion}' no soportado. Operadores permitidos: "
            f"{', '.join(_OPERACIONES_VALIDAS)}."
        )

    if operacion == "suma":
        return op1 + op2
    elif operacion == "resta":
        return op1 - op2
    elif operacion == "multiplicacion":
        return op1 * op2
    else:  # division
        if op2 == 0:
            raise ValueError(
                "No se puede dividir por cero: 'operando2' es 0 y la división por "
                "cero no está definida. Volvé a invocar la herramienta con un "
                "'operando2' distinto de 0."
            )
        return op1 / op2

simple_calc_schema = ToolSchema.from_callable(simple_calc)
