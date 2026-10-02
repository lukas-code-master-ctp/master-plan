# Animación al digitalizar el plano

## Problema

Digitalizar un plano en Mis KMZ toma de unos segundos a ~5 minutos (casi todo es el lector
de rótulos: 96 pasadas de Tesseract). Hoy el paso 3 muestra solo el registro técnico en
negro. Construir y publicar un master ya tienen una tarjeta con un dron, pasos en palabras
y una barra que avanza con las líneas reales del pipeline (`consola/web/js/vuelo.js`).

## Solución

Una tarjeta del mismo estilo en el paso 3 de la pantalla del KMZ, con escena propia:
**un escáner recorre un plano de juguete**. A medida que avanza el trabajo:

1. *Abriendo el plano*: aparece la hoja.
2. *Leyendo los números de lote*: la línea del escáner barre la hoja; los números van
   apareciendo sobre los lotes.
3. *Siguiendo los deslindes*: se dibujan las líneas.
4. *Separando los lotes*: los lotes se rellenan uno a uno.
5. *Enderezando las líneas*: quedan nítidos; al terminar, "Plano digitalizado: N lotes".

- El avance sale de las líneas del proceso, con los pasos que ya define `vuelo.js`
  (`PASOS['digitalizar-plano']`), sin temporizadores.
- En el paso 2 la barra avanza **dentro del paso** con las líneas `Rótulos: X de Y pasadas`,
  porque es el más largo.
- Si falla: la causa en palabras y el registro abierto, como en la tarjeta del dron.
- El registro técnico queda plegado debajo ("Ver el detalle técnico").
- `prefers-reduced-motion`: sin animación, solo la barra y el texto.

## Fuera del alcance

Cambiar la tarjeta del dron del master.

## Aceptación

- La tarjeta se ve mientras digitaliza y al terminar, y avanza con las líneas reales,
  incluido el avance dentro del paso de lectura.
- `node --test` cubre el cálculo del avance (con las líneas reales de un plano).
- Verificada en el navegador con un trabajo real o simulado.
