# Masterplan 360

Visor aéreo interactivo de un loteo: panorámicas 360 desde las posiciones de vuelo,
con las parcelas marcadas encima, un plano satelital sincronizado y la ficha comercial
de cada lote.

Los polígonos no están dibujados a mano. Se calculan proyectando la geometría del KMZ
sobre cada panorámica a partir del GPS del dron. Cambiar los datos y regenerar toma un
comando.

Sirve para cualquier loteo, no solo para el que se construyó primero.

## Empezar con un proyecto nuevo

Necesitas tres cosas en una carpeta:

1. **Un KMZ** con los polígonos de las parcelas y un punto por lote con su nombre
   (`LOTE A123`). Así vienen los que exporta Global Mapper.
2. **Una planilla .xlsx** con al menos una columna `Parcela`. Ver [La planilla](#la-planilla).
3. **Las panorámicas del dron**, equirectangulares y con el XMP intacto. Pueden estar
   en subcarpetas por posición de vuelo.

Los archivos se descubren por tipo, no por nombre, así que da lo mismo cómo se llamen:

```bash
pip install -r requirements.txt
python -m pipeline.construir --proyecto "C:/ruta/a/Villa seca"
```

Sin `--proyecto` busca en la carpeta que contiene a `masterplan360`.

Eso deja en `web/` un sitio completo y listo para subir. Antes de publicar conviene
revisar el calce con `python -m pipeline.qa_overlay`.

### Qué hay que ajustar a mano

- `pipeline/config.py`: `NOMBRE_PROYECTO`, `NOMBRE_ETAPA` y `WHATSAPP`.
- Las panorámicas tienen que traer su XMP. Si pasaron por un editor que lo borró, el
  pipeline no puede resolver el rumbo y no hay cómo proyectar.

## Cómo se usa

### Ver el sitio

La web necesita servirse por HTTP: abrir `index.html` con doble clic no funciona,
porque el navegador bloquea la lectura de los archivos de datos.

```bash
cd masterplan360/web && python -m http.server 8000
```

Y entrar a http://localhost:8000

En Claude Code el servidor está declarado en `.claude/launch.json` con el nombre
`masterplan360`, así que basta con abrir la vista previa.

### Publicar

Sube el contenido de `web/` a tu hosting. Es un sitio estático: no necesita PHP, ni
base de datos, ni Node en el servidor. Funciona en Netlify, Vercel, S3, cPanel o
cualquier hosting compartido.

Pesa unos 85 MB, casi todo panorámicas.

### Actualizar los datos

Editas la planilla como siempre (marcar un lote como `RESERVADO`, agregar precios,
etc.) y regeneras:

```bash
python -m pipeline.construir --sin-imagenes
```

`--sin-imagenes` salta el reprocesamiento de panorámicas, que es lo lento. Úsalo
siempre que solo hayan cambiado datos comerciales. Sin esa opción regenera todo, pero
igual se salta las imágenes que ya están al día.

Después vuelve a subir `web/datos/`.

**Ojo con la caché al actualizar.** Los archivos de datos se sirven como cualquier
otro estático, así que un visitante que ya entró puede seguir viendo los precios y
estados viejos hasta que su navegador revalide. Si tu hosting lo permite, ponle
`Cache-Control: no-cache` a `datos/` (las panorámicas sí conviene que se cacheen
largo: no cambian). En Netlify eso es un `_headers`; en Apache, un `.htaccess`.

### Revisar antes de publicar

```bash
python -m pipeline.qa_overlay
```

Deja en `control-calce/` una imagen por vista con los polígonos dibujados sobre la
panorámica. Sirve para confirmar de un vistazo que todo cae donde corresponde.

## El diseño

La fotografía manda. El cromado son pastillas claras apoyadas encima que no tapan el
terreno: cada parcela es un contorno blanco fino más un disco con su número.

**El disco es el objetivo de clic real**, no el polígono. Un número redondo se acierta
mucho mejor que el borde de una figura irregular, sobre todo con el dedo.

- **El estado lo lleva el disco, no la línea.** Al ser un color sólido se lee igual
  sobre bosque, sobre tierra y sobre cielo, y deja todos los contornos blancos y
  limpios. Blanco = disponible, amarillo = reservado, rojo = vendido.
- **Tipografías**: Fraunces (títulos; el eje *wonk* le da cualidad de grabado),
  Instrument Sans (interfaz) e IBM Plex Mono (datos: coordenadas, alturas, rótulos).
  Autoalojadas en `web/vendor/fuentes/`, 396 KB. El sitio no le pide nada a Google.
- **Ocre** para lo accionable: el botón primario, la altura activa, el punto de vuelo
  seleccionado y el anillo de la parcela elegida.

Si cambias los colores en `pipeline/config.py`, ojo con dos cosas: que el color se lea
sobre la fotografía, y que el texto del disco lo elige `datos.js` por luminancia, así
que un color claro recibe texto oscuro y viceversa, solo.

Lo único que sale a internet en tiempo de ejecución son las teselas satelitales del
plano (Esri). Si eso no te sirve, el visor 360 funciona igual sin conexión.

## La planilla

El pipeline detecta las columnas por nombre, sin distinguir tildes ni mayúsculas.
Reconoce:

| Columna | Obligatoria | Notas |
|---|---|---|
| `Parcela` | Sí | Acepta `A214`, `Lote A 420`, `LOTE A24` |
| `Estado` | No | `Disponible`, `Reservado`, `Vendido`, `No disponible` |
| `Superficie` | No | En m². Entiende `13.124` como 13.124 m² |
| `Servidumbre` | No | En metros |
| `Precio` | No | Si falta, la ficha dice "A consultar" |
| `Moneda` | No | `CLP` (por defecto) o `UF` |
| `Link de pago` | No | Puede ser distinto por parcela |

Para agregar precios basta con sumar una columna `Precio` al xlsx. No hay que tocar
código.

El teléfono de WhatsApp está en `pipeline/config.py`, en `WHATSAPP`.

## Estructura

**En el repo no está `web/datos/` ni `web/panoramas/`**: son salida del pipeline, no
código. La primera vez hay que correrlo para tener un sitio.

```
masterplan360/
├── pipeline/          Python: lee las fuentes y produce los datos
│   ├── config.py      Rutas, colores, umbrales; descubre las fuentes
│   ├── solar.py       Posición del sol y detección del disco solar
│   ├── kmz.py         Lectura del KMZ del loteo
│   ├── excel.py       Lectura de la planilla comercial
│   ├── panoramas.py   Pose de cada foto y resolución del rumbo
│   ├── proyeccion.py  Proyección de polígonos a coordenadas angulares
│   ├── imagenes.py    Niveles de imagen para la web
│   ├── construir.py   Orquestador
│   └── qa_overlay.py  Control de calce
├── web/               El sitio (se sube tal cual)
│   ├── js/            Visor WebGL, mapa, ficha, filtros
│   ├── datos/         Generado por el pipeline
│   ├── panoramas/     Generado por el pipeline
│   └── pruebas.html   Pruebas de humo en navegador
├── control-calce/     Generado por qa_overlay (no se sube)
└── docs/diseno.md     Por qué está hecho así
```

## Pruebas

```bash
python -m pytest pipeline/tests -q
node --test web/js/camara.test.js
```

Y las de navegador, con el servidor levantado: http://localhost:8000/pruebas.html

Las tres capas cubren cosas distintas. Las de Python validan la astronomía y la
geometría contra invariantes conocidas. Las de Node validan la matemática de cámara.
Las de navegador levantan la aplicación real y comprueban que el panorama se dibuja,
que los polígonos caen sobre la imagen, que las tipografías cargan y que los flujos
responden.

Las de navegador cargan `index.html` dentro de un iframe con `requestAnimationFrame`
y `ResizeObserver` parcheados por temporizador. Sin eso no corren en una pestaña de
fondo, donde el navegador congela ambos.

## Cómo se resuelve el rumbo de cada panorámica

Es la parte no obvia. Para proyectar hay que saber hacia dónde apunta la columna x=0
de cada panorámica, y las fotos no traen `GPano:PoseHeadingDegrees`.

`drone-dji:GimbalYawDegree` sí viene, pero no sirve: DJI graba el yaw de un
sub-fotograma arbitrario del stitching. Medido contra el norte real, el desfase es
+2° en las posiciones 01 y 02, y +212° en las 03 y 04.

La solución es el sol. Con la hora de captura y las coordenadas se calcula su azimut
real (algoritmo NOAA), y en la imagen el sol aparece como un disco saturado
inconfundible. La diferencia entre ambos da el rumbo.

El pipeline informa el error de elevación de cada detección: si el sol detectado está
a la altura que predice la astronomía, es el sol. En las 13 panorámicas el error es
menor a 1°.

## Deudas conocidas del primer proyecto

Esto es del armado de Hacienda Vichuquén, no del sistema. Se deja acá porque los dos
primeros problemas se repiten en cualquier loteo y conviene detectarlos temprano.

1. **El KMZ está incompleto.** Cubre 105 lotes ("solo lotes a alzarse"), de los cuales
   103 están en la planilla. Las otras 99 parcelas disponibles aparecen en el buscador
   y el listado con su ficha completa, marcadas como "sin vista aérea", pero no tienen
   polígono. Al reemplazar el KMZ por el completo y regenerar, aparecen solas.

   Se nota sobre todo en la posición 02: los lotes que están justo bajo el dron
   (292, 293, 300, 301) no están en el KMZ, así que esa vista solo muestra parcelas
   lejanas.

2. **Terreno plano.** La proyección asume el suelo a la altura del punto de despegue.
   Produce un desfase vertical leve en las parcelas más lejanas. Si consigues las
   curvas de nivel del loteo, `proyeccion.py` acepta un modelo de elevación y el calce
   queda exacto sin cambiar nada más.

3. **Sin precios.** La planilla no los trae y el link de pago es uno solo genérico
   para las 202 parcelas. Ver la tabla de columnas más arriba.

4. **Las fotos de POSICIÓN 03 están mal rotuladas.** El archivo "50 METROS" es de
   100 m y el "100 METROS" es de 300 m. El pipeline usa la altura del XMP, no el
   nombre, así que salen bien; pero conviene renombrarlas en el Drive.
