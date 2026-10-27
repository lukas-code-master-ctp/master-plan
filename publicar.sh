#!/usr/bin/env bash
# publicar.sh — Sube al hosting el sitio ya construido de un loteo.
#
#   ./publicar.sh <carpeta-del-sitio> <proyecto-en-vercel> [--crear | --crear-si-falta] [--dominio <host>]
#
# La consola dice qué publicar y cómo se llama el proyecto; el script no deduce
# nada. Eso importa: el nombre del proyecto es la identidad del loteo en el
# hosting, y deducirlo del nombre del loteo hacía que dos clientes con el mismo
# nombre se pisaran el sitio.
#
# `--crear` solo la primera vez. Si el proyecto ya existe, `vercel project add`
# falla y el script **muere**: ese error es justamente la colisión que antes se
# tragaba un `|| true` y terminaba desplegando encima del sitio de otro.
#
# `--crear-si-falta` es para volver a publicar un loteo que se bajó del aire
# (despublicar.sh): el nombre ya es suyo en la consola, así que si el proyecto
# sigue en el hosting se usa, y si el hosting lo borró se crea de nuevo.
#
# `--dominio` (p. ej. praderas.tumasterplan.cl) se le pide al hosting en cada
# publicación, así un loteo publicado antes de tener dominio lo gana al republicar.
# Si el hosting no lo acepta, el loteo se publica igual en su .vercel.app y se avisa.
#
# Al terminar deja <sitio>/../publicacion.json con la URL fija del loteo (el
# alias de producción que dio el hosting), para que la consola la guarde en vez
# de adivinarla.
set -euo pipefail
cd "$(dirname "$0")"

sitio="${1:?uso: ./publicar.sh <carpeta-del-sitio> <proyecto-en-vercel> [--crear | --crear-si-falta] [--dominio <host>]}"
proyecto="${2:?falta el nombre del proyecto en el hosting}"
shift 2
crear=""
dominio=""
while [ $# -gt 0 ]; do
  case "$1" in
    --crear) crear="--crear" ;;
    --crear-si-falta) crear="--crear-si-falta" ;;
    --dominio) dominio="${2:?falta el host de --dominio}"; shift ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

# El equipo Pro. No es un detalle de cuenta: el plan Hobby prohíbe el uso
# comercial —"Hobby teams are restricted to non-commercial personal use only"—
# y estos sitios venden parcelas. Apuntar al equipo equivocado además crea un
# proyecto nuevo con el mismo nombre y bifurca el sitio publicado.
scope="${VERCEL_SCOPE:-lrencoret-1882s-projects}"
# En el contenedor no hay sesión interactiva: el token viene por variable. Acá,
# con la sesión del CLI, el array queda vacío — y bash 3.2, el que trae macOS,
# considera "unbound" la expansión de un array vacío bajo `set -u`. De ahí el
# `${token[@]+...}`: expande a nada cuando no hay token, en vez de morirse.
token=()
[ -n "${VERCEL_TOKEN:-}" ] && token=(--token "$VERCEL_TOKEN")

if [ ! -f "$sitio/index.html" ]; then
  echo "no existe $sitio/index.html: hay que construir el loteo antes de publicarlo" >&2
  exit 1
fi

echo "▶ Publicando $sitio como $proyecto en $scope"

if [ "$crear" = "--crear" ]; then
  # Sin `|| true`: si el nombre ya está tomado, esto tiene que fallar.
  vercel project add "$proyecto" --scope "$scope" ${token[@]+"${token[@]}"}
elif [ "$crear" = "--crear-si-falta" ]; then
  if ! respuesta=$(vercel project add "$proyecto" --scope "$scope" ${token[@]+"${token[@]}"} 2>&1); then
    printf '%s\n' "$respuesta" | grep -qi 'already' || { printf '%s\n' "$respuesta" >&2; exit 1; }
  fi
fi

vercel link --yes --project "$proyecto" --scope "$scope" ${token[@]+"${token[@]}"} --cwd "$sitio" >/dev/null
salida=$(vercel deploy --prod --yes --scope "$scope" ${token[@]+"${token[@]}"} --cwd "$sitio")
echo "$salida"

# Ya asignado a este mismo proyecto es lo normal desde la segunda publicación; en
# otro proyecto, no: ese dominio es de otro loteo y no se toca.
propio_pedido=""
if [ -n "$dominio" ]; then
  if respuesta=$(vercel domains add "$dominio" "$proyecto" --scope "$scope" ${token[@]+"${token[@]}"} 2>&1) \
     || { printf '%s\n' "$respuesta" | grep -qi 'already' \
          && ! printf '%s\n' "$respuesta" | grep -qiE 'another|different'; }; then
    propio_pedido="https://$dominio"
  else
    printf '%s\n' "$respuesta" >&2
    echo "⚠ No se pudo asignar $dominio: el loteo queda en su dirección de vercel.app" >&2
  fi
fi

# La URL de ESTE despliegue (`…-5huo5t5m5.vercel.app`): cambia en cada
# publicación. `vercel deploy` imprime un JSON cuando el CLI no está en una
# terminal; si no, la última línea con https.
#
# Además de https se acepta http, pero solo a la propia máquina (127.0.0.1 o
# localhost, con o sin puerto): es lo que imprime el `vercel` falso de QA local
# (qa/bin/vercel). El real nunca devuelve http, así que en producción no cambia nada.
url_valida='^(https://|http://(127\.0\.0\.1|localhost)(:[0-9]+)?(/|$))'
despliegue=$(printf '%s\n' "$salida" | grep -oE 'https?://[^"[:space:]]+' | grep -E "$url_valida" | tail -1)

# La que hay que guardar es la fija del loteo: uno de los alias de producción.
# Primero un dominio propio (<slug>.tumasterplan.cl) si lo tiene; si no, el
# alias .vercel.app más corto, que es el nombre del proyecto (el otro lleva
# pegado el nombre del equipo). Sin alias, queda la del despliegue.
alias_=$(vercel inspect "$despliegue" --scope "$scope" ${token[@]+"${token[@]}"} 2>&1 \
  | awk '/^ *Aliases/ {dentro=1; next} dentro && /https?:\/\// {print $NF; next} dentro && /^ *[A-Z]/ {exit}' \
  | grep -E "$url_valida" || true)
propio=$(printf '%s\n' "$alias_" | grep -v '\.vercel\.app$' | grep -E "$url_valida" | head -1 || true)
corto=$(printf '%s\n' "$alias_" | grep '\.vercel\.app$' | awk '{print length, $0}' | sort -n | head -1 | cut -d' ' -f2- || true)
url="${propio_pedido:-${propio:-${corto:-$despliegue}}}"

printf '{"proyecto": "%s", "url": "%s", "despliegue": "%s"}\n' "$proyecto" "$url" "$despliegue" \
  > "$sitio/../publicacion.json"
echo "▶ URL publicada: $url"
