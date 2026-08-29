#!/usr/bin/env bash
# Barrido de prompt x max-history-messages x max-iterations, 5 trials por
# combinación. Prueba los 3 prompts que hay en prompts/:
#   - baseline_prompt.txt   (prompt corto/genérico)
#   - long_prompt.txt       (prompt largo estructurado, sin registro de estado)
#   - long_prompt_estado.txt (el anterior + instrucción de registro de estado)
#
# Uso:
#   bash corridas.sh
#
# Genera un label por combinación: <prompt>-t5-h<H>-i<I>
# Resultados en eval/results/<label>/ (summary.json, summary.md, case_*.json).
# Logs por combinación en eval/results/_logs/<label>.log (stdout+stderr de
# ese `eval/run.py`) — con corridas en paralelo, la salida por terminal se
# intercala entre combinaciones y no es legible directamente.
#
# Ajustá PROMPT_NAMES/PROMPT_FILES o HISTORY_VALUES/ITER_VALUES si querés
# otro paso o rango — con los valores por defecto son 3 prompts x 4 valores
# de historial x 4 de iteraciones = 48 combinaciones x 5 trials x 8
# escenarios = 1920 casos en total. Cada caso ronda ~10s (max_iterations=10)
# a ~65s (max_iterations=100) según lo medido en corridas anteriores — un
# barrido de este tamaño corrido en serie tarda del orden de un día y
# medio. `PARALLEL_JOBS` corre varias combinaciones a la vez (cada una es
# independiente: label propio, sin estado compartido) para bajar ese
# tiempo de pared en proporción.
#
# OJO con subirlo: el cupo on-demand de Bedrock para Nova Lite es 200
# requests/min (`aws service-quotas list-service-quotas --service-code
# bedrock`), pero ya medimos con CloudWatch (`InvocationThrottles` en el
# namespace `AWS/Bedrock`) que con solo 2 procesos corriendo a la vez el
# 44% de los intentos rebotó por throttling (pico de 362 invocaciones/min
# contra el cupo de 200). El agente reintenta solo, así que un caso no
# falla por esto, pero cada rebote es tiempo desperdiciado sin progreso —
# más `PARALLEL_JOBS` no garantiza correr más rápido si ya estás saturando
# el cupo. Empezá bajo (2) y mirá `InvocationThrottles` durante una
# corrida chica antes de subirlo:
#   aws cloudwatch get-metric-statistics --namespace AWS/Bedrock \
#     --metric-name InvocationThrottles --period 60 --statistics Sum \
#     --start-time <ISO> --end-time <ISO> --region us-east-1

set -euo pipefail
cd "$(dirname "$0")"

TRIALS=5
PARALLEL_JOBS=2
PROMPT_NAMES=(baseline long estado)
PROMPT_FILES=(
  "prompts/baseline_prompt.txt"
  "prompts/long_prompt.txt"
  "prompts/long_prompt_estado.txt"
)
HISTORY_VALUES=(50 100 150 200)
ITER_VALUES=(50 100 150 200)

LOG_DIR="eval/results/_logs"
mkdir -p "$LOG_DIR"

commands_file="$(mktemp)"
trap 'rm -f "$commands_file"' EXIT

for p_idx in "${!PROMPT_NAMES[@]}"; do
  prompt_name="${PROMPT_NAMES[$p_idx]}"
  prompt_file="${PROMPT_FILES[$p_idx]}"

  for h in "${HISTORY_VALUES[@]}"; do
    for i in "${ITER_VALUES[@]}"; do
      label="${prompt_name}-t${TRIALS}-h${h}-i${i}"
      echo "echo '# iniciando ${label}' >&2; python eval/run.py --scenarios all --trials ${TRIALS} --label ${label} --system-prompt-file ${prompt_file} --max-history-messages ${h} --max-iterations ${i} > ${LOG_DIR}/${label}.log 2>&1; echo '# terminó ${label} (ver ${LOG_DIR}/${label}.log)' >&2" \
        >> "$commands_file"
    done
  done
done

total=$(wc -l < "$commands_file" | tr -d ' ')
echo "# Barrido: ${#PROMPT_NAMES[@]} prompts x ${#HISTORY_VALUES[@]} valores de historial x ${#ITER_VALUES[@]} valores de iteraciones = ${total} corridas, ${PARALLEL_JOBS} en paralelo" >&2

xargs -P "$PARALLEL_JOBS" -I{} bash -c '{}' < "$commands_file"

echo >&2
echo "# Barrido completo: ${total} corridas en eval/results/ (logs en ${LOG_DIR}/)" >&2
