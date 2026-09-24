#!/usr/bin/env bash
# consola.sh — Abre la consola de Tu Masterplan en el navegador.
#
#   ./consola.sh
#
# Corre en este computador, donde ya están las fotos: una carpeta de panorámicas
# pesa unos 200 MB y subirlas a otro lado para procesarlas acá no tiene sentido.
set -euo pipefail
cd "$(dirname "$0")"

PUERTO="${PUERTO:-8780}"
PYTHON=.venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3

echo "▶ Consola en http://localhost:$PUERTO"
( sleep 1.2; open "http://localhost:$PUERTO" 2>/dev/null || true ) &
exec "$PYTHON" -m uvicorn consola.app:app --host 127.0.0.1 --port "$PUERTO" --log-level warning
