# mia_agents — Andamiaje del trabajo del curso

Van a construir un framework mínimo de agentes en Python a lo largo de
tres milestones. Este repositorio es su punto de partida.

La documentación está organizada para que avancen por etapas:

1. **Primero preparen el entorno y completen el M1.** Esa es la parte
   central de este README.
2. **Después lean la sección de M2** cuando toque añadir memoria,
   salida estructurada y resiliencia.
3. **Finalmente lean la sección de M3** cuando el framework se use para
   resolver y evaluar escenarios del mundo simulado.

Los requisitos formales de cada entrega están separados por milestone:
[`ENUNCIADO_M1.md`](../ENUNCIADO_M1.md),
[`ENUNCIADO_M2.md`](../ENUNCIADO_M2.md) y
[`ENUNCIADO_M3.md`](../ENUNCIADO_M3.md).


## Estructura del repositorio
```
scaffold/
├── mia_agents/             # FIJO (no editar). Tipos compartidos, protocolos,
│   ├── types.py            # ToolSchema, LLMResponse, AgentResult, ...
│   ├── tool_schema.py      # ToolSchema.from_callable (genera JSON Schema)
│   ├── protocols.py        # contratos Agent y LLMClient
│   ├── llm_client.py       # Bedrock/Ollama; traduce ToolSchema al proveedor
│   ├── cli.py
│   └── testing/
├── mia_world/              # FIJO (no editar). Mundo simulado de M3:
│   ├── state.py            #   modelo de estado, herramientas genéricas
│   ├── tools.py            #   (look/examine/take/use) y comprobador de
│   ├── scenarios.py        #   meta. Los estudiantes registran estas
│   └── goals.py            #   herramientas en su agente para resolver M3.
├── scenarios/              # FIJO (no editar). Escenarios JSON de M3.
│   └── *.json
├── scripts/                # Utilidades para probar proveedores LLM.
│   └── bedrock_llm_smoke.py
├── student_framework/      # SUYO. Implementen acá el agente.
│   ├── __init__.py         # exporta `build_agent` (único punto de entrada)
│   ├── agent.py            # clase MyAgent implementa run + register_tool
│   └── tools/              # añadir aquí sus herramientas
└── tests/
    └── conformance/        # FIJO (no editar). Tests que toda entrega debe pasar.
        ├── test_m1.py
        ├── test_m2.py
        └── test_m3_world.py
```

> **FIJO** quiere decir que esos archivos no son editables. Volvemos a
> ejecutar los tests de conformidad tal y como aparecen aquí; si sus
> modificaciones a los archivos FIJOS provocan divergencia, el milestone no
> aprueba.

## Primeros pasos

### 1. Requisitos previos

- **Python 3.10 o superior**. Comprueben la versión:
  ```bash
  python3 --version
  ```
  Si tienen una versión anterior, instalen una nueva con
  [pyenv](https://github.com/pyenv/pyenv) o desde
  [python.org](https://www.python.org/downloads/).

  > **Importante (usuarios de pyenv):** el comando `python3 -m venv .venv`
  > del paso 2 usa el `python3` que esté activo en ese momento. Si tienen
  > pyenv con una versión ≥ 3.10 instalada pero `python3 --version` sigue
  > mostrando una versión vieja del sistema (p. ej. 3.9), **fijen la versión
  > en la carpeta del proyecto antes de crear el venv**:
  > ```bash
  > pyenv install 3.11.4     # solo si no la tienen instalada
  > pyenv local 3.11.4       # crea .python-version en esta carpeta
  > python3 --version        # verifiquen: debe decir 3.11.x
  > ```
  > Si no lo hacen, el venv se crea con la versión vieja y los tests fallan
  > al importar con un error críptico:
  > `TypeError: unsupported operand type(s) for |: 'type' and 'types.GenericAlias'`
  > (es la sintaxis `X | Y` que requiere Python 3.10+).
- **Git** instalado.
- **Acceso a un proveedor LLM**. El equipo docente indicará qué opción
  usar en la cursada.

### Windows — usar una terminal Bash

Las instrucciones de este README asumen una shell **Bash** (`export`,
`source .venv/bin/activate`, etc.). En Windows el **Símbolo del sistema**
y **PowerShell** no son equivalentes; usen una de estas opciones y sigan
los mismos bloques `bash` que aparecen más abajo.

#### Opción recomendada: WSL2 (Ubuntu)

Con **WSL** (Windows Subsystem for Linux) tienen un entorno Linux real
dentro de Windows: los comandos del README funcionan **sin cambios**.

1. Abran **PowerShell o Terminal como administrador** y ejecuten (una sola
   vez; puede pedir reinicio):
   ```powershell
   wsl --install
   ```
   Si ya tenían WSL, comprueben la versión: `wsl --version` (WSL 2).
2. Reinicien si Windows lo pide, abran la app **Ubuntu** (o la distro que
   instalaron) desde el menú Inicio.
3. Dentro de Ubuntu, instalen Python y Git si faltan:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip git
   python3 --version   # debe ser ≥ 3.10
   ```
4. Clonen el repo **dentro del home de Linux** (p. ej. `~/repos/...`), no
   solo bajo `C:\` montado en `/mnt/c/`, para evitar lentitud y problemas
   con el venv.
5. Desde esa terminal Ubuntu, sigan desde el paso **2. Clonar e instalar
   dependencias** tal como está escrito (`cd scaffold/`, `source
   .venv/bin/activate`, `export`, `pytest`, etc.).

**Cursor / VS Code:** pueden abrir la carpeta del proyecto con
*Remote - WSL* para editar y usar la terminal integrada ya en Bash.

Documentación: [Instalar WSL](https://learn.microsoft.com/es-es/windows/wsl/install).

#### Alternativa: Git Bash

Si no pueden usar WSL, instalen [Git for Windows](https://git-scm.com/download/win)
y abran **Git Bash**. Ahí `export` y `pytest` suelen funcionar, pero hay
dos diferencias habituales:

| En Linux / WSL | En Git Bash (Windows) |
|----------------|------------------------|
| `source .venv/bin/activate` | `source .venv/Scripts/activate` |
| `python3` | A veces solo `python`; comprueben con `python --version` |

Instalen Python 3.10+ desde [python.org](https://www.python.org/downloads/)
marcando **“Add python.exe to PATH”**. Luego, en Git Bash, creen el venv
con el mismo intérprete que usarán después:

```bash
cd scaffold/
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

El resto del README (`export` de variables, `pytest`, `python -m
mia_agents.cli`, etc.) es igual; solo cambia la ruta de activación del
venv.

#### Qué evitar para este TP

- **CMD** (`cmd.exe`) y **PowerShell** sin WSL: no tienen `source` ni la
  misma sintaxis de `export`; no son la referencia del curso.
- Mezclar un venv creado en PowerShell con comandos en Git Bash (o al
  revés): creen y activen el venv siempre en la misma shell que usarán
  para trabajar.

### 2. Clonar e instalar dependencias

Desde la raíz del repositorio del grupo:

```bash
cd scaffold/

# Crear un entorno virtual para aislar las dependencias del trabajo
python3 -m venv .venv

# Activar el entorno virtual
source .venv/bin/activate          

# Instalar las dependencias del andamiaje
pip install -r requirements.txt
```

Cuando el entorno esté activo, el prompt mostrará `(.venv)` al inicio.
Para desactivarlo, ejecuten `deactivate`.

### 3. Configurar el proveedor LLM

Para ejecutar el agente contra un modelo real necesitan configurar un
proveedor. Para los tests de conformidad no hace falta: usan un cliente
LLM falso y no consumen créditos.

El andamiaje soporta dos opciones. Definan la variable de entorno
correspondiente; `LLMClient.from_env()` elige Ollama si está configurado
y, si no, Bedrock.

```bash
# Opción A — Ollama (local, sin clave)
export OLLAMA_HOST="http://localhost:11434"
export OLLAMA_MODEL="llama3.1"          # opcional, defecto: llama3.1

# Opción B — AWS Bedrock
export BEDROCK_MODEL_ID="amazon.nova-lite-v1:0"
export AWS_REGION="us-east-1"           # opcional, defecto: us-east-1
# + credenciales AWS estándar (boto3 las recoge automáticamente):
export AWS_ACCESS_KEY_ID="<su_access_key>"
export AWS_SECRET_ACCESS_KEY="<su_secret_key>"
export AWS_SESSION_TOKEN="<su_session_token>"          # opcional, para STS/SSO
```

Estas variables solo viven durante la sesión del terminal. Si quieren que
persistan, añádanlas a su `~/.bashrc` o `~/.zshrc` (en **WSL/Ubuntu** o
**Git Bash**), o creen un archivo `.env` y cárguenlo con `source .env`
antes de trabajar. No suban ese archivo al repositorio.

#### Notas opcionales de proveedor

Si usan **Ollama**, instálenlo desde [ollama.com](https://ollama.com),
arranquen el servidor (`ollama serve` o la app de macOS) y descarguen un
modelo con tool-use:

```bash
ollama pull llama3.1        # 8B, buen baseline
ollama pull qwen2.5         # 7B, alternativa
```

Si usan **AWS Bedrock**, asegúrense de que la cuenta AWS tiene acceso al
modelo elegido en la consola de Bedrock. `BedrockProvider` usa la API
Converse vía `boto3`, y `from_env()` selecciona Bedrock solamente cuando
ve `BEDROCK_MODEL_ID`; las credenciales AWS por sí solas no lo activan.

Modelos Bedrock recomendados para el trabajo:

| Modelo | Ventana de contexto | Cuándo usarlo |
|---|---:|---|
| `amazon.nova-micro-v1:0` | 128K tokens | Baseline débil. |
| `amazon.nova-lite-v1:0` | 300K tokens | Default recomendado. |
| `amazon.nova-pro-v1:0` | 300K tokens | Modelo más poderoso para validar limitaciones LLM. |

Para probar Bedrock antes de implementar el agente, usen el script de
smoke test incluido:

```bash
python scripts/bedrock_llm_smoke.py
```

El script usa `LLMClient(BedrockProvider())`, hace una llamada LLM simple
y muestra la respuesta.

### 4. Verifiquen que la instalación está bien

Antes de implementar nada, ejecuten los tests de conformidad. Deberían
**fallar** con `NotImplementedError` — eso confirma que pytest, las
dependencias y el entorno funcionan, y que solo queda implementar el
agente.

```bash
pytest tests/conformance/test_m1.py
```
### Nota: 
se corren de la siguiente forma
```bash
python3 -m pytest tests/conformance/test_m1.py
```

Si en lugar de `NotImplementedError` ven errores de importación (p. ej.
`ModuleNotFoundError`), repitan el paso 2.

## Milestone 1 — Bucle del agente y herramientas

El M1 es el núcleo del framework. En esta etapa no necesitan memoria,
resumen, salida estructurada, reintentos avanzados ni evaluación sobre
escenarios. El objetivo es tener un agente que pueda registrar
herramientas, exponerlas al LLM, ejecutarlas y devolver una respuesta
final.

### Qué implementan en M1

#### Herramientas (`student_framework/tools/`)

Patrón por herramienta (ver `tools/example.py`):

```python
from typing import Annotated
from pydantic import Field
from mia_agents.types import ToolSchema

def mi_herramienta(
    arg: Annotated[str, Field(description="Qué hace este argumento.")],
) -> str:
    """Descripción de la herramienta para el LLM (docstring completo)."""
    return "resultado como string"

mi_herramienta_schema = ToolSchema.from_callable(mi_herramienta)
```

No armen `parameters={...}` a mano: `from_callable` deriva el JSON Schema
desde la firma Python.

Necesitan **tres** herramientas obligatorias (ver [`ENUNCIADO_M1.md`](../ENUNCIADO_M1.md)):

1. **Calculadora simple** — dos operandos numéricos y operador `+`, `-`, `*`, `%`.
2. **Lector de archivos** — ruta → contenido de archivo de texto (acceso acotado).
3. **Herramienta libre** — la que quieran (mismo patrón `from_callable`).

#### Registro (`agent.py`)

```python
def register_tool(self, tool: Callable[..., str], schema: ToolSchema) -> None:
    self._tools[schema.name] = tool
    self._schemas[schema.name] = schema
```

En `build_agent` (`__init__.py`): `agent.register_tool(fn, fn_schema)` por
cada herramienta.

#### Bucle `run`

1. `self._llm.chat(messages=..., tools=list(self._schemas.values()), ...)`
   — pasan objetos `ToolSchema`; el cliente fijo llama `to_llm_spec()` y
   adapta a Bedrock/Ollama.
2. Si hay `tool_calls`: ejecutar callable, append mensaje `role: "tool"`,
   repetir.
3. Si no hay `tool_calls`: devolver `resp.content` en `AgentResult.answer`.
4. Tope `max_iterations`; registrar cada invocación en `AgentStep`.

No usen `final_result` en M1 (eso es M2).

#### Entregables adicionales

- Escenarios de prueba propios donde el agente use al menos dos herramientas.
- Informe según [`ENUNCIADO_M1.md`](../ENUNCIADO_M1.md).

Eso es todo en cuanto a código para M1. Los requisitos de informe escrito
y presentación están en [`ENUNCIADO_M1.md`](../ENUNCIADO_M1.md).

### Qué no hacen todavía

- Manejo de conversación multiturno. `run` recibe un único mensaje.
- Memoria / resumen. Eso entra en M2.
- Validación de salida estructurada con reintentos. Eso entra en M2.
- `structured_call` obligatorio con herramienta sintética `final_result`.
  Eso entra en M2 (ver abajo).
- Reintentos ante fallos transitorios. Eso entra en M2.
- Infraestructura de evaluación para el problema del mundo simulado. Eso
  entra en M3.

### Ejecutar los tests de M1

Los tests usan un cliente LLM falso (`MockLLMClient`), así que **no
consumen créditos de API** y son deterministas.

```bash
pytest tests/conformance/test_m1.py
```

Pasar este test es necesario, pero **no suficiente**: la corrección
ejecuta casos adicionales sobre el mismo contrato. El contrato completo de
M1 está en [`ENUNCIADO_M1.md`](../ENUNCIADO_M1.md); impleméntenlo contra ese
documento, no contra casos puntuales.

### Ejecutar su agente

El runner CLI estandarizado importa su `build_agent` y ejecuta el agente
con el mensaje que indiquen:

```bash
python -m mia_agents.cli run --module student_framework \
  --message "¿Cuánto es 17 * 23? Usá la calculadora."
```

- `--module student_framework` — el paquete Python que exporta `build_agent`.
- `--message "..."` — el mensaje que recibirá el agente.

La salida es un `AgentResult` serializado como JSON, listo para
inspeccionar o conectar con herramientas de evaluación. Requiere tener
la clave de API configurada (paso 3) porque hace llamadas reales al LLM.

## Milestone 2 — Memoria y robustez

Lean esta sección recién cuando el M1 esté aprobado. En M2 se mantiene la
misma interfaz externa (`build_agent`, `register_tool`, `run`), pero el
agente empieza a comportarse como un sistema conversacional más robusto.

### Qué cambia en M2

- `run(...)` pasa a tener un **estado**: llamadas sucesivas sobre la misma
  instancia continúan la conversación.
- El agente respeta `max_history_messages`: la lista de mensajes enviada
  al LLM no puede crecer sin límite.
- `structured_call(...)` debe cerrar con un `tool_call` obligatorio a
  **`final_result`**, validar sus `arguments` y reintentar con reparación
  si falla (ver nota siguiente).
- Las llamadas al LLM y a herramientas deben manejar errores de forma
  limpia; los fallos transitorios se reintentan.
- `AgentResult.input_tokens` y `AgentResult.output_tokens` acumulan los
  tokens reportados por el proveedor cuando estén disponibles.

Los requisitos completos de este milestone están en
[`ENUNCIADO_M2.md`](../ENUNCIADO_M2.md).

### Ejecutar los tests de M2

Cuando estén trabajando en este milestone, ejecuten los tests de M2 así:

```bash
pytest tests/conformance/test_m2.py
```

También conviene seguir ejecutando M1:

```bash
pytest tests/conformance/test_m1.py
pytest tests/conformance/test_m2.py
```

### Herramienta sintética `final_result` (obligatoria en `structured_call`)

En M1 el bucle de `run(...)` termina cuando el modelo devuelve texto sin
`tool_calls`. En M2, **`structured_call(...)`** debe ofrecer al LLM la tool
interna **`final_result`** (nombre fijo: `mia_agents.FINAL_RESULT_TOOL_NAME`).
Armen el esquema con `final_result_tool_schema(schema)` o
`ToolSchema.from_model(schema, name="final_result", ...)`. No la registren
con `register_tool`: es sintética; el agente valida los `arguments` del
`tool_call` y reintenta con contexto de reparación si fallan.

Los tests de **`run`** siguen usando el cierre de M1 (texto sin tools).
Los de **`structured_call`** exigen `final_result` en la lista `tools` de
la primera llamada y validación/reparación sobre sus `arguments`.

`BedrockProvider` no implementa `response_format`; en `structured_call`
no dependan de ese parámetro — usen `final_result`.

## Milestone 3 — Mundo simulado y evaluación

El equipo docente proporciona en `mia_world/` un mundo simulado tipo
sala de escape y, en `scenarios/`, cuatro escenarios de dificultad
creciente (`easy`, `medium`, `hard`, `extreme`).

```bash
# Listar los escenarios disponibles
python -m mia_world.cli list

# Ejecutar uno (por dificultad, por id o por path)
python -m mia_world.cli run --scenario easy
python -m mia_world.cli run --scenario color-locks
python -m mia_world.cli run --scenario scenarios/03-hard-library-search.json
```

`run` importa su `build_agent`, le registra las herramientas del
mundo simulado y le pasa el `user_message` del escenario. Imprime el
`AgentResult`, el estado de la meta (`goal_achieved`) y los pasos.
El proceso termina con código de salida 0 si el escenario se resolvió,
1 si no. Requiere una clave de API válida.

### Ejecutar los tests de M3

Los tests actuales de M3 verifican la consistencia del mundo simulado y
sus escenarios. No ejecutan un LLM real.

```bash
pytest tests/conformance/test_m3_world.py
```

El M3 completo también requiere su propia infraestructura de evaluación
para correr el agente, capturar resultados, analizar errores y comparar
ablaciones. Ese entregable está descrito en [`ENUNCIADO_M3.md`](../ENUNCIADO_M3.md).

### Nota sobre contexto con Ollama

El `num_ctx` por defecto de Ollama es **2048 tokens**, insuficiente para
los escenarios largos de M3. El `OllamaProvider` del framework lo
sobreescribe a 16 384. Si construyen el provider a mano y necesitan otro
valor, pásenlo en el constructor:

```python
from mia_agents.llm_client import LLMClient, OllamaProvider

client = LLMClient(OllamaProvider(model="llama3.1", num_ctx=32768))
```

## Tests útiles por etapa

```bash
pytest tests/conformance/test_m1.py                       # Milestone 1
pytest tests/conformance/test_m2.py                       # Milestone 2
pytest tests/conformance/test_m3_world.py                 # Milestone 3 (mundo)
pytest tests/test_ollama_provider.py                      # Provider Ollama (mockeado)
pytest tests/test_bedrock_provider.py                     # Provider Bedrock (mockeado)
```

## ¿Y si necesitan otro proveedor de LLM?

No editen `mia_agents/llm_client.py`. En su lugar, implementen su propia
clase en `student_framework/` que satisfaga el protocolo
`mia_agents.protocols.LLMClient` (un único método `chat(...) -> LLMResponse`)
y pásenla al agente vía `build_agent({"llm_client": su_cliente})`. El
`MockLLMClient` de los tests es un ejemplo de esa misma sustitución.

## Problemas comunes

- **`ModuleNotFoundError: No module named 'mia_agents'`** — el entorno
  virtual no está activo o las dependencias no se instalaron. Repitan el
  paso 2.
- **Error de proveedor LLM al ejecutar la CLI** — falta configurar una
  de las opciones del paso 3. Los tests de conformidad no requieren
  clave, pero la CLI sí.
- **Los tests fallan con `NotImplementedError`** — no es un fallo del
  andamiaje; significa que aún no implementaron `MyAgent.run` o
  `MyAgent.register_tool`.
