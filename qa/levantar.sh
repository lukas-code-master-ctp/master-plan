#!/usr/bin/env bash
# qa/levantar.sh — Deja la consola corriendo en esta máquina, con datos de prueba
# y sin tocar nada de afuera.
#
#   npm run qa:levantar               # de cero: borra .qa/, siembra y levanta
#   npm run qa:levantar -- --conservar  # levanta sobre el .qa/ que ya había
#
# Levanta tres cosas en segundo plano: la consola (hypercorn), la Cierra falsa y un
# servidor de lo que publica el `vercel` falso. Sus PID quedan en .qa/pids/ y sus
# registros en .qa/logs/. `npm run qa:bajar` las termina.
#
# Los puertos se cambian con QA_PUERTO_CONSOLA, QA_PUERTO_CIERRA y
# QA_PUERTO_PUBLICADOS.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="$(pwd -P)"
QA="$REPO/.qa"

conservar=""
for argumento in "$@"; do
  case "$argumento" in
    --conservar) conservar=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "✗ No conozco '$argumento'. Uso: qa/levantar.sh [--conservar]" >&2; exit 2 ;;
  esac
done

QA_PUERTO_CONSOLA="${QA_PUERTO_CONSOLA:-8780}"
QA_PUERTO_CIERRA="${QA_PUERTO_CIERRA:-8791}"
QA_PUERTO_PUBLICADOS="${QA_PUERTO_PUBLICADOS:-8792}"

# --- lo que haya quedado de la vez anterior --------------------------------------

# Primero bajar: si se borra .qa/ con los procesos arriba, se pierden sus PID y
# quedan ocupando los puertos sin que nadie sepa cómo matarlos.
if [ -d "$QA/pids" ] && [ -n "$(ls -A "$QA/pids" 2>/dev/null)" ]; then
  bash "$REPO/qa/bajar.sh"
fi

# --- dependencias ----------------------------------------------------------------

if ! python3 -c "import fastapi, hypercorn, sqlalchemy, passlib, PIL, numpy, shapely, fitz, cv2, pyproj" &>/dev/null; then
  echo "▶ Instalando las dependencias de Python..."
  python3 -m pip install -q -r requirements.txt -r requirements-consola.txt
fi

if python3 -m hypercorn --help >/dev/null 2>&1; then
  HYPERCORN=(python3 -m hypercorn)
elif command -v hypercorn >/dev/null 2>&1; then
  HYPERCORN=(hypercorn)
else
  echo "✗ No encuentro hypercorn (ni 'python3 -m hypercorn' ni el ejecutable)." >&2
  exit 1
fi
command -v curl >/dev/null 2>&1 || { echo "✗ Hace falta curl para ver si la consola contesta." >&2; exit 1; }

# --- entorno propio --------------------------------------------------------------

# Todo lo que podría apuntar a un servicio de verdad se vacía antes de fijar lo
# nuestro: un hilo con credenciales en el entorno tampoco se escapa.
unset MASTERPLAN_BD SENDGRID_API_KEY EMAIL_FROM GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET \
      VERCEL_TOKEN VERCEL_SCOPE CIERRA_API_URL CONSOLA_URL MASTERPLAN_DOMINIO \
      MASTERPLAN_CRM_CSV CONSOLA_REPUBLICAR_AL_ARRANCAR

export CONSOLA_ENTORNO=local
export MASTERPLAN_DATOS="$QA/datos"
# Fijo y público a propósito: firma galletas de una consola que solo vive acá.
export CONSOLA_SECRETO="qa-local-solo-pruebas"
export CONSOLA_BUZON="$QA/buzon"
export QA_BUZON="$CONSOLA_BUZON"
export CIERRA_API_URL="http://127.0.0.1:$QA_PUERTO_CIERRA"
export QA_PUBLICADOS="$QA/publicados"
export QA_URL_PUBLICADOS="http://127.0.0.1:$QA_PUERTO_PUBLICADOS"
export QA_URL_CONSOLA="http://127.0.0.1:$QA_PUERTO_CONSOLA"
export QA_PUERTO_CONSOLA QA_PUERTO_CIERRA QA_PUERTO_PUBLICADOS
# El `vercel` falso primero: publicar.sh (el de verdad) lo encuentra a él.
export PATH="$REPO/qa/bin:$PATH"
export VERCEL_SCOPE=qa-local
export PYTHONUNBUFFERED=1

# --- puertos ---------------------------------------------------------------------

# Antes de borrar .qa/: con un puerto ocupado no se levanta nada, y no hay por
# qué perder los datos de la corrida anterior.
puerto_libre() {
  python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

ocupados=""
for par in "QA_PUERTO_CONSOLA:$QA_PUERTO_CONSOLA" "QA_PUERTO_CIERRA:$QA_PUERTO_CIERRA" \
           "QA_PUERTO_PUBLICADOS:$QA_PUERTO_PUBLICADOS"; do
  variable="${par%%:*}"; puerto="${par#*:}"
  if ! puerto_libre "$puerto"; then
    echo "✗ El puerto $puerto está ocupado. Libéralo o elige otro con $variable=<puerto>." >&2
    ocupados=1
  fi
done
[ -z "$ocupados" ] || exit 1

# --- .qa/ ------------------------------------------------------------------------

if [ -z "$conservar" ]; then
  # Se borra con ruta absoluta y solo si es exactamente <repo>/.qa: un cd que
  # falló o un REPO vacío no pueden terminar en un rm sobre otra cosa.
  case "$QA" in
    /*/.qa) ;;
    *) echo "✗ Ruta de .qa rara ('$QA'): no borro nada." >&2; exit 1 ;;
  esac
  [ "$(dirname "$QA")" = "$REPO" ] && [ -f "$REPO/qa/levantar.sh" ] \
    || { echo "✗ $QA no está dentro del repo: no borro nada." >&2; exit 1; }
  rm -rf -- "$QA"
elif [ ! -d "$QA/datos" ]; then
  echo "✗ --conservar, pero no hay $QA/datos: corre sin --conservar la primera vez." >&2
  exit 1
fi
mkdir -p "$QA/datos" "$QA/buzon" "$QA/publicados" "$QA/pids" "$QA/logs"

# --- procesos --------------------------------------------------------------------

# setsid: cada proceso queda como jefe de su propio grupo, así qa:bajar mata
# también a sus hijos (hypercorn corre la consola en un proceso aparte).
en_segundo_plano() {
  local nombre="$1"; shift
  setsid nohup "$@" >"$QA/logs/$nombre.log" 2>&1 </dev/null &
  echo $! >"$QA/pids/$nombre.pid"
}

cola_del_registro() {
  echo "  Lo último de .qa/logs/$1.log:" >&2
  tail -n 25 "$QA/logs/$1.log" 2>/dev/null | sed 's/^/    /' >&2 || true
}

# Espera a que <url> conteste <código> (por defecto 200), hasta ~30 s.
esperar() {
  local nombre="$1" url="$2" esperado="${3:-200}" codigo=""
  for _ in $(seq 1 60); do
    codigo="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$url" || true)"
    [ "$codigo" = "$esperado" ] && return 0
    if ! kill -0 "$(cat "$QA/pids/$nombre.pid")" 2>/dev/null; then
      echo "✗ $nombre se cayó al arrancar." >&2
      cola_del_registro "$nombre"
      exit 1
    fi
    sleep 0.5
  done
  echo "✗ $nombre no contestó $esperado en $url (lo último: ${codigo:-nada})." >&2
  cola_del_registro "$nombre"
  exit 1
}

# Si algo falla (o Ctrl-C) desde acá hasta el final, se baja lo que alcanzó a
# levantarse: nada queda colgado ocupando puertos.
listo=""
trap '[ -n "$listo" ] || bash "$REPO/qa/bajar.sh" >&2' EXIT
trap 'exit 130' INT TERM

echo "▶ Levantando la Cierra falsa y el servidor de lo publicado..."
en_segundo_plano cierra_falsa python3 -m qa.cierra_falsa --puerto "$QA_PUERTO_CIERRA"
en_segundo_plano publicados python3 -m http.server "$QA_PUERTO_PUBLICADOS" \
  --bind 127.0.0.1 --directory "$QA/publicados"
# Sin clave, la Cierra falsa contesta 401: con eso basta para saber que está.
esperar cierra_falsa "$CIERRA_API_URL/integrations/proyectos" 401
esperar publicados "$QA_URL_PUBLICADOS/"

if [ -z "$conservar" ]; then
  echo "▶ Sembrando (construye y publica Praderas Demo, tarda unos segundos)..."
  if ! python3 -m qa.sembrar; then
    echo "✗ La siembra falló." >&2
    exit 1
  fi
else
  echo "▶ --conservar: no siembro, uso los datos que ya estaban en .qa/."
fi

echo "▶ Levantando la consola..."
en_segundo_plano consola "${HYPERCORN[@]}" 'consola.app:crear_app()' \
  --bind "127.0.0.1:$QA_PUERTO_CONSOLA" --workers 1
esperar consola "$QA_URL_CONSOLA/entrar"
listo=1

# --- para los demás --------------------------------------------------------------

# Para que otros comandos (o una persona) usen la misma consola:
#   source .qa/entorno.sh
{
  echo "# Lo escribió qa/levantar.sh. Uso: source .qa/entorno.sh"
  echo "unset MASTERPLAN_BD SENDGRID_API_KEY EMAIL_FROM GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET VERCEL_TOKEN CONSOLA_URL MASTERPLAN_DOMINIO MASTERPLAN_CRM_CSV CONSOLA_REPUBLICAR_AL_ARRANCAR"
  for variable in CONSOLA_ENTORNO MASTERPLAN_DATOS CONSOLA_SECRETO CONSOLA_BUZON QA_BUZON \
                  CIERRA_API_URL QA_PUBLICADOS QA_URL_PUBLICADOS QA_URL_CONSOLA \
                  QA_PUERTO_CONSOLA QA_PUERTO_CIERRA QA_PUERTO_PUBLICADOS VERCEL_SCOPE \
                  PYTHONUNBUFFERED; do
    printf 'export %s=%q\n' "$variable" "${!variable}"
  done
  printf 'export PATH=%q:"$PATH"\n' "$REPO/qa/bin"
} >"$QA/entorno.sh"

clave_cierra="$(python3 -c 'from qa.cierra_falsa import CLAVE; print(CLAVE)')"

echo
echo "✓ QA local arriba"
echo "  Consola         $QA_URL_CONSOLA"
echo "  Cierra falsa    $CIERRA_API_URL  (clave: $clave_cierra)"
echo "  Publicados      $QA_URL_PUBLICADOS/"
for sitio in "$QA/publicados"/*/; do
  [ -d "$sitio" ] || continue
  echo "                  $QA_URL_PUBLICADOS/$(basename "$sitio")/"
done
echo
python3 - <<'PY'
from qa.sembrar import CLAVE_QA, CUENTAS
print(f"▶ Cuentas (clave de todas: {CLAVE_QA})")
ancho = max(len(a) for a in CUENTAS)
for alias, correo in CUENTAS.items():
    nota = "  (sin confirmar el correo: no entra)" if alias == "sinconfirmar" else ""
    print(f"  {alias.ljust(ancho)}  {correo}{nota}")
PY
echo
echo "▶ Comandos"
echo "  npm run qa:captura -- --como duenio --ruta '#/planos'"
echo "  npm run qa:correos            # --ultimo: solo el enlace del último"
echo "  npm run qa:bajar"
echo "  source .qa/entorno.sh         # el mismo entorno en otra terminal"
echo "  Registros en .qa/logs/"
