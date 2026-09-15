# CONDITIONS — edge benchmark v1.5.0, 2026-09-15
node: taipan-edge (192.168.1.64), Rocky 10.2, kernel 6.12.0-211.49.1.el10_2.x86_64
gpu: NVIDIA GeForce RTX 5090, 32607 MiB, 610.57.04
vllm pid: 92846 (api server); engine: 93009, 29564 MiB
launch line: bash -c ~/bench/venv/bin/pip install -q ninja 2>&1 | tail -1; ls ~/bench/venv/bin/ninja && nohup setsid env PATH="$HOME/bench/venv/bin:$PATH" ~/.venvs/codex-pacific-vllm/bin/python -m vllm.entrypoints.openai.api_server --model /home/gompert/bench/models/gpt-oss-20b --served-model-name openai/gpt-oss-20b --host 127.0.0.1 --port 8000 --max-model-len 126976 --gpu-memory-utilization 0.90 --max-num-seqs 8 --seed 0 --enforce-eager --enable-auto-tool-choice --tool-call-parser openai > ~/bench/logs/vllm
vllm/torch: Name: vllm Version: 0.25.0 Name: torch Version: 2.11.0 
model: /home/gompert/bench/models/gpt-oss-20b = pool snapshot 6cee5e81ee83 rsynced -rtL from jl-i (same bytes production serves)
repo: v1.5.0 = 831d39e757755dc31da0e1fc33b2a909c47bbf48
mission venv: py3.12.14, freeze at ~/bench/venv-freeze.txt (47 pkgs; EDGE interpreter — not production pins)
run: start 2026-09-15T14:04:01Z, done 2026-09-15T14:35:08Z, EXIT=0
env: LOCAL_API_BASE=127.0.0.1:8000, JUDAIS_LOBI_MAX_OUTPUT_TOKENS=8192, temp 0.2, mcp stub (in-repo), skill bench_skill.md
CAVEAT: edge row is its own interpreter (5090/py3.12/vLLM-0.25); arms internally paired; never beside pool L4 rows.
