#!/usr/bin/env bash
# despublicar.sh — Baja del aire el sitio de un loteo.
#
#   ./despublicar.sh <proyecto-en-vercel>
#
# Borra todos los despliegues del proyecto: la dirección (y su dominio
# <slug>.tumasterplan.cl) queda respondiendo "no encontrado". El proyecto en sí
# se queda, para que al publicar de nuevo el loteo vuelva con el mismo nombre.
# La consola lo llama cuando la loteadora o CTP aprietan "Bajar del aire", y
# cuando un plan lleva más de 7 días vencido (consola/vencimientos.py).
set -euo pipefail
cd "$(dirname "$0")"

proyecto="${1:?uso: ./despublicar.sh <proyecto-en-vercel>}"
# Lo mismo que publicar.sh: el equipo Pro y el token del contenedor.
scope="${VERCEL_SCOPE:-lrencoret-1882s-projects}"
token=()
[ -n "${VERCEL_TOKEN:-}" ] && token=(--token "$VERCEL_TOKEN")

echo "▶ Bajando del aire $proyecto en $scope"
vercel remove "$proyecto" --yes --scope "$scope" ${token[@]+"${token[@]}"}
echo "▶ $proyecto ya no está en línea"
