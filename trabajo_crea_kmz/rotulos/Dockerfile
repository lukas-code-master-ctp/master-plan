# Imagen de prueba para medir Tesseract sobre los planos (tarea 1 de Crea tu KMZ).
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytesseract opencv-python-headless numpy pillow
# Una hebra por proceso de Tesseract: las pasadas ya corren en paralelo (sin esto, 10x mas lento).
ENV OMP_THREAD_LIMIT=1
WORKDIR /w
