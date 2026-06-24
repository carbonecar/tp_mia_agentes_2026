"""
Calculadora simple que permite realizar operaciones basicas como suma, resta, division y 
multiplicacion con solo dos parámetros.
"""

from typing import Annotated
from pydantic import Field
from mia_agents.types import ToolSchema
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
    if operacion == "suma":
        return operando1 + operando2
    elif operacion == "resta":
        return operando1 - operando2
    elif operacion == "multiplicacion":
        return operando1 * operando2
    elif operacion == "division":
        if operando2 == 0:
            raise ValueError("No se puede dividir por cero.")
        return operando1 / operando2
    else:
        raise ValueError("Operación no válida. Use 'suma', 'resta', 'multiplicacion' o 'division'.")    

simple_calc_schema = ToolSchema.from_callable(simple_calc)