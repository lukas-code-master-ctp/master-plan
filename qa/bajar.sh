#!/usr/bin/env bash
# qa/bajar.sh — Termina lo que levantó qa/levantar.sh.
#
#   npm run qa:bajar
#
# Mata los procesos de .qa/pids/ (con sus hijos: cada uno es jefe de su grupo) y
# borra los .pid. No toca los datos: .qa/ queda para `qa:levantar -- --conservar`.
# Si no hay nada arriba, lo dice y sale bien.
#
# Antes de mandar señales confirma que el PID sigue siendo el proceso que lanzó
# qa/levantar.sh (por su línea de comando): un .pid viejo puede apuntar a un
# proceso ajeno que reusó el número, y a ese no se le toca.
#
# QA_DIR cambia la carpeta .qa/ (solo para las pruebas).
set -euo pipefail
cd "$(dirname "$0")/.."

QA="${QA_DIR:-$(pwd -P)/.qa}"
PIDS="$QA/pids"

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

# La línea de comando del PID, con espacios entre argumentos. /proc en Linux;
# ps donde no hay (macOS).
linea_de_comando() {
  if [ -r "/proc/$1/cmdline" ]; then
    tr '\0' ' ' <"/proc/$1/cmdline" 2>/dev/null || true
  else
    ps -o args= -p "$1" 2>/dev/null || true
  fi
}

# Lo que tiene que aparecer en la línea de comando de cada proceso de
# qa/levantar.sh, un fragmento por línea.
huella() {
  case "$1" in
    cierra_falsa) echo "qa.cierra_falsa" ;;
    publicados) echo "http.server"; echo "$QA/publicados" ;;
    consola) echo "hypercorn"; echo "consola.app" ;;
  esac
}

# ¿Tiene la línea $1 todos los fragmentos de $2 (uno por línea)?
coincide() {
  local fragmento
  while IFS= read -r fragmento; do
    case "$1" in
      *"$fragmento"*) ;;
      *) return 1 ;;
    esac
  done <<EOF
$2
EOF
}

es_de_qa() {
  local linea grupo fragmentos
  fragmentos="$(huella "$1")"
  [ -n "$fragmentos" ] || return 1
  if kill -0 "$2" 2>/dev/null; then
    linea="$(linea_de_comando "$2")"
    [ -n "$linea" ] && coincide "$linea" "$fragmentos"
    return
  fi
  # El jefe ya murió pero el grupo sigue. El número pudo reusarlo otro jefe de
  # grupo que también murió (un demonio que hace doble fork, por ejemplo), así
  # que el grupo es nuestro solo si algún miembro tiene la huella.
  while read -r grupo linea; do
    [ "$grupo" = "$2" ] && coincide "$linea" "$fragmentos" && return 0
  done <<EOF
$(ps -A -o pgid= -o args= 2>/dev/null || true)
EOF
  return 1
}

for archivo in "${archivos[@]}"; do
  nombre="$(basename "$archivo" .pid)"
  pid="$(cat "$archivo" 2>/dev/null || true)"
  if ! [[ "$pid" =~ ^[0-9]+$ ]] || ! vivo "$pid"; then
    echo "  $nombre ya no estaba corriendo"
    rm -f -- "$archivo"
    continue
  fi
  if ! es_de_qa "$nombre" "$pid"; then
    echo "  el PID $pid ya no es $nombre (lo usa otro proceso): no lo toco"
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
