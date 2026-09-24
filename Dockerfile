# La consola de Tu Masterplan, en Cloud Run.
#
# Lleva Python para el pipeline y Node solo para el CLI de Vercel, que es lo que
# publica el sitio de cada loteo. Hypercorn en vez de uvicorn porque sirve HTTP/2
# en claro: sin eso Cloud Run corta las peticiones en 32 MiB y una panorámica pesa
# más de 60.
FROM python:3.13-slim

# Node para el CLI de Vercel; tini para que Ctrl-C y los reinicios maten de verdad
# a los subprocesos del pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
      nodejs npm tini \
    && npm install -g vercel@59 \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-consola.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt -r requirements-consola.txt

COPY pipeline/ pipeline/
COPY consola/ consola/
COPY web/ web/
COPY publicar.sh ./

# El volumen con los datos se monta acá: proyectos, salidas y cachés.
ENV MASTERPLAN_DATOS=/datos \
    CONSOLA_ENTORNO=produccion \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Sin privilegios: si algún día hay una ejecución remota, que no sea como root.
RUN useradd --create-home --uid 1000 consola && mkdir -p /datos && chown consola /datos /app
USER consola

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "hypercorn --factory consola.app:crear_app --bind 0.0.0.0:$PORT --workers 1"]
