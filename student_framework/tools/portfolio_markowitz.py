"""
Optimizador de carteras según el modelo de Markowitz (varianza mínima).
"""

import json
from typing import Annotated

import numpy as np
from pydantic import Field

from mia_agents.types import ToolSchema


def optimizar_portfolio_markowitz(
    retornos_historicos: Annotated[
        dict[str, list[float]],
        Field(
            description=(
                "Retornos historicos por activo: clave = nombre del activo, "
                "valor = lista de retornos periodicos. Todas las listas deben "
                "tener la misma longitud."
            )
        ),
    ],
) -> str:
    """Calcula los pesos del portfolio de varianza minima (modelo de Markowitz).

    A partir de series de retornos historicos por activo, calcula la matriz
    de covarianza muestral y resuelve en forma cerrada el portfolio que
    minimiza el riesgo total (varianza), sujeto a que los pesos sumen 1.
    No restringe los pesos a ser positivos: permite posiciones en corto.

    Args:
        retornos_historicos (dict[str, list[float]]): retornos por activo.

    Returns:
        str: JSON con los pesos optimos por activo, el retorno esperado del
        portfolio y su desvio estandar (riesgo).
    """
    activos = list(retornos_historicos.keys())
    if len(activos) < 2:
        raise ValueError("Se necesitan al menos dos activos para optimizar un portfolio.")

    longitudes = {len(v) for v in retornos_historicos.values()}
    if len(longitudes) != 1:
        raise ValueError("Todas las series de retornos deben tener la misma longitud.")
    if longitudes.pop() < 2:
        raise ValueError("Cada serie de retornos debe tener al menos dos observaciones.")

    matriz_retornos = np.array([retornos_historicos[a] for a in activos])
    covarianza = np.cov(matriz_retornos)
    medias = matriz_retornos.mean(axis=1)

    unos = np.ones(len(activos))
    try:
        covarianza_inv = np.linalg.inv(covarianza)
    except np.linalg.LinAlgError:
        raise ValueError("La matriz de covarianza es singular; no se puede optimizar con estos datos.")

    pesos = covarianza_inv @ unos / (unos @ covarianza_inv @ unos)

    retorno_portfolio = float(pesos @ medias)
    riesgo_portfolio = float(np.sqrt(pesos @ covarianza @ pesos))

    resultado = {
        "pesos": {activo: round(float(peso), 6) for activo, peso in zip(activos, pesos)},
        "retorno_esperado": round(retorno_portfolio, 6),
        "riesgo_portfolio": round(riesgo_portfolio, 6),
    }
    return json.dumps(resultado, ensure_ascii=False)


optimizar_portfolio_markowitz_schema = ToolSchema.from_callable(optimizar_portfolio_markowitz)
