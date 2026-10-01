#!/usr/bin/env bash
# publicar.sh — Sube al hosting el sitio ya construido de un loteo.
#
#   ./publicar.sh <carpeta-del-sitio> <proyecto-en-vercel> [--crear]
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
# Al terminar deja <sitio>/../publicacion.json con la URL fija del loteo (el
# alias de producción que dio el hosting), para que la consola la guarde en vez
# de adivinarla.
set -euo pipefail
cd "$(dirname "$0")"

sitio="${1:?uso: ./publicar.sh <carpeta-del-sitio> <proyecto-en-vercel> [--crear]}"
proyecto="${2:?falta el nombre del proyecto en el hosting}"
crear="${3:-}"

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
fi

vercel link --yes --project "$proyecto" --scope "$scope" ${token[@]+"${token[@]}"} --cwd "$sitio" >/dev/null
salida=$(vercel deploy --prod --yes --scope "$scope" ${token[@]+"${token[@]}"} --cwd "$sitio")
echo "$salida"

# La URL de ESTE despliegue (`…-5huo5t5m5.vercel.app`): cambia en cada
# publicación. `vercel deploy` imprime un JSON cuando el CLI no está en una
# terminal; si no, la última línea con https.
despliegue=$(printf '%s\n' "$salida" | grep -oE 'https://[^"[:space:]]+' | tail -1)

# La que hay que guardar es la fija del loteo: uno de los alias de producción.
# Primero un dominio propio (<slug>.tumasterplan.cl) si lo tiene; si no, el
# alias .vercel.app más corto, que es el nombre del proyecto (el otro lleva
# pegado el nombre del equipo). Sin alias, queda la del despliegue.
alias_=$(vercel inspect "$despliegue" --scope "$scope" ${token[@]+"${token[@]}"} 2>&1 \
  | awk '/^ *Aliases/ {dentro=1; next} dentro && /https:\/\// {print $NF; next} dentro && /^ *[A-Z]/ {exit}' \
  || true)
propio=$(printf '%s\n' "$alias_" | grep -v '\.vercel\.app$' | grep '^https://' | head -1 || true)
corto=$(printf '%s\n' "$alias_" | grep '\.vercel\.app$' | awk '{print length, $0}' | sort -n | head -1 | cut -d' ' -f2- || true)
url="${propio:-${corto:-$despliegue}}"

printf '{"proyecto": "%s", "url": "%s", "despliegue": "%s"}\n' "$proyecto" "$url" "$despliegue" \
  > "$sitio/../publicacion.json"
echo "▶ URL publicada: $url"
