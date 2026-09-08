# 1. flat, sin mapa (baseline de siempre)
python eval/run.py --scenarios all --trials 3 --label flat-t3-h100-i100-baseline-v8 \
  --max-iterations 100 --max-history-messages 100 \
  --system-prompt-file prompts/long_prompt_estado.txt

# 2. flat + mapa
python eval/run.py --scenarios all --trials 3 --label flat-t3-h100-i100-baseline-mapa-v8 \
  --max-iterations 100 --max-history-messages 100 \
  --system-prompt-file prompts/long_prompt_estado_mapa.txt --room-graph

# 3. planner + mapa
python eval/run.py --scenarios all --trials 3 --label planner-t3-h100-i100-mapa-v8 \
  --max-iterations 100 --max-history-messages 100 \
  --system-prompt-file prompts/long_prompt_estado_mapa.txt --room-graph \
  --planner

# 4. subagent + mapa
python eval/run.py --scenarios all --trials 3 --label subagent-t3-h100-i100-mapa-v8 \
  --max-iterations 100 --max-history-messages 100 \
  --system-prompt-file prompts/long_prompt_estado_mapa.txt --room-graph \
  --agent-mode subagent

# 5. adaptive + mapa
python eval/run.py --scenarios all --trials 3 --label adaptive-t3-h100-i100-mapa-v8 \
  --max-iterations 100 --max-history-messages 100 \
  --system-prompt-file prompts/long_prompt_estado_mapa.txt --room-graph \
  --agent-mode adaptive --adaptive
