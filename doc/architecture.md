# Arquitectura del proyecto

## Diagrama de clases y módulos

Ver [classes.mmd](classes.mmd).

## Flujo de ejecución (bucle agentico)

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant MyAgent
    participant LLMClient
    participant Tool

    User->>CLI: python -m mia_agents run --message "..."
    CLI->>MyAgent: build_agent() → agent.run(message)

    loop Bucle agentico (max_iterations)
        MyAgent->>LLMClient: chat(messages, tools=[ToolSchema...], system)
        LLMClient-->>MyAgent: LLMResponse

        alt LLMResponse tiene tool_calls
            loop Por cada ToolCall
                MyAgent->>Tool: fn(**kwargs)
                Tool-->>MyAgent: str (resultado)
                MyAgent->>MyAgent: AgentStep registrado
            end
            MyAgent->>MyAgent: Agrega tool results al historial
        else LLMResponse tiene content (sin tool_calls)
            MyAgent-->>CLI: AgentResult(answer, steps, tokens)
        end
    end

    CLI-->>User: JSON(AgentResult)
```

## Flujo de structured_call (M2)

```mermaid
sequenceDiagram
    participant Caller
    participant MyAgent
    participant LLMClient

    Caller->>MyAgent: structured_call(prompt, Schema, max_repair_attempts)

    loop Hasta max_repair_attempts
        MyAgent->>LLMClient: chat(messages, tools=[final_result_tool_schema(Schema)])
        LLMClient-->>MyAgent: LLMResponse

        alt tool_call a "final_result" con args válidos
            MyAgent->>MyAgent: Schema.model_validate(arguments)
            MyAgent-->>Caller: instancia de Schema ✅
        else texto libre o args inválidos
            MyAgent->>MyAgent: construye mensaje de reparación con contexto del fallo
        end
    end

    MyAgent-->>Caller: Exception (agotó reintentos) ❌
```

## Resumen de la arquitectura

| Capa | Módulo | Responsabilidad |
|---|---|---|
| Framework fijo | `mia_agents/` | Tipos, protocolos, proveedores LLM, CLI, testing |
| Proveedores LLM | `llm_client.py` | Adapta mensajes y tools para Ollama y AWS Bedrock |
| A implementar | `student_framework/` | `MyAgent` con bucle agentico, historial y salida estructurada |
| Tests | `tests/conformance/` | Verifican el contrato `Agent` sin APIs externas (MockLLMClient) |

**Proveedores disponibles:**
- `OllamaProvider` — LLM local vía `OLLAMA_HOST` + `OLLAMA_MODEL`
- `BedrockProvider` — AWS Bedrock vía `BEDROCK_MODEL_ID` + credenciales AWS
- `MockLLMClient` — respuestas prefabricadas para tests deterministas
