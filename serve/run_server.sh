#!/usr/bin/env bash
# Serve a seccal GGUF with llama.cpp, grammar-constrained and deterministic.
#
#   serve/run_server.sh models/LFM2.5-1.2B-Instruct-Q4_K_M.gguf
#
# Env overrides: SECCAL_PORT (8089), SECCAL_HOST (127.0.0.1), SECCAL_CTX (2048),
#                SECCAL_NGL (99: offload everything to Metal/GPU).
set -euo pipefail

MODEL="${1:?usage: run_server.sh <path/to/model.gguf>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRAMMAR="$HERE/seccal.gbnf"

exec llama-server \
  -m "$MODEL" \
  --jinja \
  --grammar-file "$GRAMMAR" \
  --temp 0 \
  --host "${SECCAL_HOST:-127.0.0.1}" \
  --port "${SECCAL_PORT:-8089}" \
  -c "${SECCAL_CTX:-2048}" \
  -ngl "${SECCAL_NGL:-99}" \
  --no-webui
