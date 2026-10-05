#!/usr/bin/env bash
# qa/bajar.sh — Termina lo que levantó qa/levantar.sh.
#
#   npm run qa:bajar
#
# Mata los procesos de .qa/pids/ (con sus hijos: cada uno es jefe de su grupo) y
# borra los .pid. No toca los datos: .qa/ queda para `qa:levantar -- --conservar`.
# Si no hay nada arriba, lo dice y sale bien.
set -euo pipefail
cd "$(dirname "$0")/.."

PIDS="$(pwd -P)/.qa/pids"

shopt -s nullglob
archivos=("$PIDS"/*.pid)
if [ ${#archivos[@]} -eq 0 ]; then
  echo "▶ No había nada de QA arriba."
  exit 0
fi

# Señal al grupo entero y, si el grupo ya no existe, al proceso solo.
senal() {
  kill "-$1" -- "-$2" 2>/dev/null || kill "-$1" "$2" 2>/dev/null || true
}

vivo() {
  kill -0 -- "-$1" 2>/dev/null || kill -0 "$1" 2>/dev/null
}

for archivo in "${archivos[@]}"; do
  nombre="$(basename "$archivo" .pid)"
  pid="$(cat "$archivo" 2>/dev/null || true)"
  if ! [[ "$pid" =~ ^[0-9]+$ ]] || ! vivo "$pid"; then
    echo "  $nombre ya no estaba corriendo"
    rm -f -- "$archivo"
    continue
  fi
  senal TERM "$pid"
  for _ in $(seq 1 20); do
    vivo "$pid" || break
    sleep 0.25
  done
  if vivo "$pid"; then
    senal KILL "$pid"
    echo "✓ $nombre bajado a la fuerza (PID $pid)"
  else
    echo "✓ $nombre bajado (PID $pid)"
  fi
  rm -f -- "$archivo"
done
