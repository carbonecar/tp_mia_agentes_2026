"""Paquete propio del grupo.

Implementen el agente en `agent.py` y registren sus herramientas a
continuación, en `build_agent`. Tanto el runner de la CLI como los tests
de conformidad llaman a `build_agent`, por lo que esta es la única puerta
de entrada pública de su entrega.
"""

from __future__ import annotations

from typing import Any

from mia_agents.llm_client import LLMClient
from mia_agents.protocols import Agent

from .agent import MyAgent


def build_agent(config: dict[str, Any] | None = None) -> Agent:
    """Construye y configura su agente.

    `config` es opcional. Si se proporciona `config["llm_client"]`, el
    agente debe usarlo (así es como los tests de conformidad inyectan un
    cliente mock). Si no, se construye a partir del entorno.

    TODO (M1): instancien su agente y llamen a `agent.register_tool(...)`
    por cada una de sus herramientas antes de devolverlo.
    """

    config = config or {} #NO CAMBIAR
    llm = config.get("llm_client") or LLMClient.from_env() #NO CAMBIAR
    kwargs: dict[str, Any] = {"llm_client": llm} #NO CAMBIAR
    
    if "max_history_messages" in config:
        kwargs["max_history_messages"] = config["max_history_messages"]
    # Overrides opcionales usados por la infraestructura de evaluación de M3
    # (eval/) para correr experimentos sin tocar build_agent por cada uno.
    optional_keys_list = (
        "max_iterations",
        "system_prompt",
        "max_llm_retries",
        "max_tool_retries",
        "retry_backoff_seconds",
    )
    for optional_key in optional_keys_list:
        if optional_key in config:
            kwargs[optional_key] = config[optional_key]

    agent = MyAgent(**kwargs)

    # Ejemplo de registro (elimínenlo cuando sus herramientas estén listas):
    # from student_framework.tools.example import reverse_string, reverse_string_schema
    # agent.register_tool(reverse_string, reverse_string_schema)
    from student_framework.tools.simple_calc import simple_calc, simple_calc_schema
    from student_framework.tools.lector_archivos import leer_archivo, leer_archivo_schema
    from student_framework.tools.portfolio_markowitz import (
        optimizar_portfolio_markowitz,
        optimizar_portfolio_markowitz_schema,
    )
    agent.register_tool(simple_calc, simple_calc_schema)
    agent.register_tool(leer_archivo, leer_archivo_schema)
    agent.register_tool(optimizar_portfolio_markowitz, optimizar_portfolio_markowitz_schema)


    return agent
