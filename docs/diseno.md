# Tu Masterplan — notas de diseño (Hacienda Vichuquén, el primer loteo)

Diseño aprobado el 2026-07-30.

## Problema

Hacienda Vichuquén Etapa 1 tiene 202 parcelas disponibles. Existe un tour 360 hecho por
un proveedor externo (3DVista, alojado en latitud360.cl) con los polígonos de cada
parcela dibujados a mano sobre las panorámicas. Queremos un producto propio que sirva
para tres cosas a la vez: vender desde la web, apoyar al ejecutivo comercial en reunión,
y dejar de depender del proveedor para actualizar datos.

## Materia prima

| Fuente | Contenido |
|---|---|
| 17 panorámicas equirectangulares | 14400×7200 px, Mavic 4 Cine, 4 posiciones × 50/100/300/500 m |
| XMP/EXIF de cada foto | GPS, altura relativa y absoluta, hora de captura |
| `KMZ HACIENDA VICHUQUEN SOLO LOTES A ALZARSE.kmz` | 116 polígonos, 105 etiquetas `LOTE A###` |
| `datos_masterplan.xlsx` | 202 parcelas: superficie, servidumbre, estado, link de pago |
| 4 capturas de referencia | Ubicación de cada vuelo sobre el plano del loteo |

## Idea central

Los polígonos **no se dibujan a mano**. Se proyectan matemáticamente: conociendo la
posición GPS del dron, su altura sobre el terreno y el rumbo de la panorámica, cada
vértice de parcela tiene un azimut y una elevación calculables. Esto da overlays exactos
en las 17 vistas, y se regeneran solos cuando cambian los datos.

### El rumbo de la panorámica

Las fotos no traen `GPano:PoseHeadingDegrees`. `drone-dji:GimbalYawDegree` existe pero no
sirve: DJI graba el yaw de un sub-fotograma arbitrario del stitching, y el desfase contra
el norte real varía entre vuelos (medimos +2° en las posiciones 01 y 02, +212° en las 03 y 04).

La solución es el sol. Con la hora de captura y las coordenadas se calcula el azimut solar
real (algoritmo NOAA); en la imagen el sol aparece como un disco saturado inconfundible.
La diferencia entre ambos da el rumbo de la columna x=0.

Validado en la posición 01: azimut solar calculado 279,3°, medido en la imagen 279,9°.
Error 0,6°.

### Supuesto de terreno

La proyección asume el suelo plano a la altura del despegue. Produce un desfase vertical
leve en parcelas lejanas. El pipeline acepta un modelo de elevación opcional; si se
consiguen las curvas de nivel del loteo, el calce mejora sin cambiar nada más.

## Arquitectura

```
masterplan360/
├── pipeline/       Python. KMZ + Excel + fotos → JSON e imágenes.
├── web/            Sitio estático. Se sube tal cual, sin compilar.
└── control-calce/  Imágenes de revisión. No se suben.
```

El pipeline corre en el PC cuando cambian los datos. La web solo lee archivos estáticos.

### Pipeline

| Módulo | Responsabilidad |
|---|---|
| `solar.py` | Posición solar (NOAA) y detección del disco solar en la panorámica |
| `kmz.py` | KMZ → polígonos con nombre normalizado |
| `excel.py` | xlsx → fichas comerciales con IDs normalizados |
| `panoramas.py` | XMP/EXIF → pose de cada vista; resuelve el rumbo |
| `proyeccion.py` | Polígonos → anillos (azimut, elevación), con subdivisión adaptativa |
| `imagenes.py` | Niveles progresivos 2048 / 4096 / 8192 px |
| `construir.py` | Orquesta y escribe la salida |
| `qa_overlay.py` | Genera las 17 imágenes de control de calce |

### Formato de salida

Las coordenadas del overlay se guardan como **(azimut, elevación) en grados**, no como
píxeles. Así el overlay es independiente del tamaño de imagen que se sirva, y el visor
convierte a dirección 3D directamente.

- `web/datos/parcelas.json` — fichas comerciales + geometría geográfica
- `web/datos/vistas.json` — índice de las vistas con su pose y cuál abrir primero
- `web/datos/vistas/<id>.json` — overlay de una vista (se carga solo al abrirla)
- `web/panoramas/<id>/{previa,media,alta}.jpg`

El pipeline escribe dentro de `web/` a propósito: esa carpeta queda autocontenida y se
sube al hosting tal cual.

### Web

Visor: WebGL propio. Un cuadrilátero a pantalla completa y un fragment shader que
convierte la dirección de cada píxel a coordenada equirectangular. Sin geometría de
esfera, sin costuras, y la misma matemática de cámara alimenta el overlay.

Overlay: SVG sobre el canvas. Líneas nítidas, hover y clic nativos, estilos por CSS.

Mapa: Leaflet sobre imagen satelital Esri (sin API key), sincronizado en ambos sentidos
con el visor.

## Dirección visual

> **Septiembre de 2026.** El sitio pasó al sistema visual de Cierra: Plus Jakarta
> Sans, grises zinc con verde `#007c10`, tarjetas con borde y sombra mínima, pills
> de estado con los tonos de la app. Lo que sigue describe la dirección editorial
> original (Fraunces + ocre): sigue vigente lo que dice sobre jerarquía, sobre que
> la fotografía manda y sobre cómo se marca una parcela; la paleta y las
> tipografías ya no.

La fotografía manda. El cromado son pastillas claras apoyadas encima: cada parcela es
un contorno blanco fino más un disco con su número, y el resto de la interfaz son
píldoras del mismo material repartidas por los bordes.

**El disco es el objetivo de clic**, no el polígono: un número redondo se acierta
mucho mejor que el borde de una figura irregular, sobre todo con el dedo.

**El estado lo lleva el disco, no la línea.** Al ser un color sólido se lee igual
sobre bosque, sobre tierra y sobre cielo. Eso deja todos los contornos blancos y
limpios, y evita el problema de fondo: sobre un paisaje de pino y tierra ocre, casi
ningún color de línea se lee bien en todas partes.

El color del texto del disco no se codifica a mano: `datos.js` lo elige por
luminancia del color de estado, así que un estado claro recibe texto oscuro y uno
oscuro texto blanco, sin que haya que acordarse.

Tipografías autoalojadas: Fraunces para títulos (el eje *wonk* le da cualidad de
grabado antiguo), Instrument Sans para interfaz, IBM Plex Mono para datos.

Dos cosas que solo se descubren mirando el resultado, no leyendo el CSS:

1. Cualquier texto que flote libre sobre la fotografía necesita placa o sombra
   fuerte. Un rótulo gris sobre cielo brillante no se ve.
2. Con "disponible" en blanco, cualquier elemento que herede ese color como texto
   desaparece. El color va solo en el punto, nunca en el contenedor.

## Decisiones

- **Sitio estático, datos desde Excel.** Sin backend, sin login, sin base de datos.
- **Niveles progresivos en vez de mosaicos.** Una textura por nivel es más simple que un
  sistema de tiles y a 8192 px da 22,8 px/grado, suficiente para web.
- **Las parcelas sin geometría no desaparecen.** Aparecen en buscador y listado marcadas
  como "sin vista aérea". Cuando llegue el KMZ completo se regeneran solas.

## Fuera de alcance

Panel de administración, login, y reconstruir las parcelas faltantes vectorizando las
capturas satelitales.

## Deudas conocidas

1. El KMZ cubre 105 lotes; 99 de los 202 disponibles no tienen geometría.
2. El Excel no trae precios y usa un único link de pago genérico.
3. Las fotos de POSICIÓN 03 están mal rotuladas (son de 100 m y 300 m, no 50 y 100).
   El pipeline usa la altura del XMP, no el nombre del archivo.
