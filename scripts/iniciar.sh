#!/usr/bin/env bash
# Inicia o Robofael usando o ambiente virtual do projeto.
# Exemplos: scripts/iniciar.sh --avatar selfie   |   scripts/iniciar.sh --continuo
set -euo pipefail
cd "$(dirname "$0")/.."
# Filtra os avisos do servidor JACK que o PyAudio imprime ao listar dispositivos
exec .venv/bin/python -m robofael "$@" 2> >(grep -v -E "^(Cannot connect|jack server|JackShm)" >&2)
