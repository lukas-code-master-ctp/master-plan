# Tu Masterplan

Visor aéreo interactivo de un loteo: panorámicas 360 desde las posiciones de vuelo,
con las parcelas marcadas encima, un plano satelital sincronizado y la ficha comercial
de cada lote.

Los polígonos no están dibujados a mano. Se calculan proyectando la geometría del KMZ
sobre cada panorámica a partir del GPS del dron. Cambiar los datos y regenerar toma un
comando.

Sirve para cualquier loteo, no solo para el que se construyó primero.

## Empezar con un proyecto nuevo

La forma cómoda es la consola:

```bash
./consola.sh
```

Abre http://localhost:8780 en el navegador. Ahí arrastras la carpeta del vuelo,
completas los datos del loteo, aprietas **Construir**, miras el control de calce y
recién entonces **Publicar**. Corre en este computador a propósito: una carpeta de
panorámicas pesa unos 200 MB y no tiene sentido subirlas a otro lado para
procesarlas acá al lado. Si la carpeta ya está en el disco, en "usar una carpeta que
ya está en este computador" se registra sin copiar nada.

La primera vez el script crea la cuenta de casa e **imprime por pantalla una clave
provisional**. Anótala y cámbiala al entrar: no se vuelve a mostrar.

Todo lo que hace la consola se puede hacer a mano, y es lo que sigue.

### Lo que necesita un loteo

Una carpeta con:

1. **Un KMZ** del loteo. Sirven los dos formatos que exporta Global Mapper: polígonos
   con un punto por lote (`LOTE A123`), o el dibujo CAD tal cual, como red de líneas
   con un punto por lote. Ver [El KMZ](#el-kmz).
2. **Las panorámicas del dron**, equirectangulares y con el XMP intacto. Da lo mismo
   en qué subcarpetas vengan o si la misma foto está dos veces: las tomas se agrupan
   por GPS y se numeran en orden de captura.
3. **`proyecto.json`** con el nombre del loteo (opcional; sin él se usa el nombre de la
   carpeta). Es lo mismo que edita el botón "Datos" de la consola:

   ```json
   {"nombre": "Praderas de Cauquenes", "etapa": "Etapas 1 a 4", "whatsapp": "56912345678",
    "despegue": [-72.27591, -35.86774],
    "referencias": ["Cauquenes", "Pelluhue", "Chanco"]}
   ```

   `despegue` es dónde despegó el dron (lon, lat). Importa más de lo que parece: ver
   [El terreno](#el-terreno). `referencias` son pueblos u otros hitos que se rotulan
   en el horizonte ("CAUQUENES · 12 KM") para que el visitante se ubique; van por
   nombre (se geocodifican solos, eligiendo el homónimo más cercano) o como
   `{"nombre": …, "lon": …, "lat": …}`.

4. **Una planilla .xlsx** con los datos comerciales (opcional). Si no hay, salen del
   export del CRM. Ver [La planilla](#la-planilla).

### A mano

Los archivos se descubren por tipo, no por nombre, así que da lo mismo cómo se llamen:

```bash
pip install -r requirements.txt
python -m pipeline.construir --proyecto "/ruta/a/Cauquenes_170926"
```

Eso deja en `salidas/praderas-de-cauquenes/sitio/` un sitio completo y listo para
subir (unos 20 MB por cada tres panorámicas, casi todo imágenes). Antes de publicar
conviene revisar el calce:

```bash
python -m pipeline.qa_overlay --proyecto "/ruta/a/Cauquenes_170926"
```

Todo lo que dice `proyecto.json` se puede pasar o pisar por línea de comandos:
`--nombre`, `--etapa`, `--whatsapp`, `--parcelacion`, `--despegue`, `--referencias`,
`--salida`, `--crm`, `--sin-crm`.

### El slug: la identidad del loteo

`proyecto.json` puede llevar un `slug`. Es la identidad del loteo —su carpeta de
salida, su proyecto en el hosting y su URL— y **se asigna una vez**: no cambia aunque
cambie el nombre, y dos loteos que se llamen igual tienen slugs distintos. Sin slug
guardado se sugiere uno del nombre, que es lo que pasa con una carpeta suelta en este
computador.

`vercel_proyecto` y `url_publicada` se escriben solos al publicar, leídos de lo que
responde el hosting. No se tocan a mano.

## Cómo se usa

### Ver el sitio

La web necesita servirse por HTTP: abrir `index.html` con doble clic no funciona,
porque el navegador bloquea la lectura de los archivos de datos.

```bash
cd masterplan360/salidas && python -m http.server 8000
```

Y entrar a http://localhost:8000/praderas-de-cauquenes/sitio/ (cada proyecto
construido tiene su carpeta).

En Claude Code el servidor está declarado en `.claude/launch.json`, así que basta
con abrir la vista previa.

### Publicar

Desde la consola, con el botón **Publicar**. A mano:

```bash
./publicar.sh salidas/<loteo>/sitio masterplan-<loteo> [--crear]
```

El script no deduce nada: recibe qué publicar y cómo se llama el proyecto en el
hosting, porque ese nombre es la identidad del loteo y deducirlo del nombre hacía que
dos loteos homónimos se pisaran el sitio. `--crear` va **solo la primera vez**; si el
proyecto ya existe, `vercel project add` falla y el script muere, que es exactamente
lo que antes se tragaba un `|| true`. Al terminar deja `publicacion.json` con la URL
real, que la consola guarda.

Necesita el CLI (`npm i -g vercel`) y `vercel login`, o `VERCEL_TOKEN` en el
contenedor. Publica en la cuenta de CTP; `VERCEL_SCOPE=<equipo>` lo manda a otro.

`web/vercel.json` va dentro de cada sitio y fija las cabeceras: `datos/` sin caché
(para que los estados y precios se vean al tiro), panorámicas cacheadas 30 días, y
una CSP que solo deja cargar lo propio más las teselas satelitales de Esri.
`pruebas.html` no se sube (`.vercelignore`).

Es un sitio estático, así que también sirve cualquier otro hosting (Netlify, S3,
cPanel): basta con subir la carpeta.

### Actualizar los datos

Cuando cambian los estados o los precios (en la planilla o en el CRM), regeneras:

```bash
python -m pipeline.construir --proyecto "/ruta/a/Cauquenes_170926" --sin-imagenes
```

`--sin-imagenes` salta el reprocesamiento de panorámicas, que es lo lento. Úsalo
siempre que solo hayan cambiado datos comerciales. Sin esa opción regenera todo, pero
igual se salta las imágenes que ya están al día.

Después, `./publicar.sh` de nuevo (o vuelve a subir `sitio/datos/`).

**Ojo con la caché al actualizar.** Los archivos de datos se sirven como cualquier
otro estático, así que un visitante que ya entró puede seguir viendo los precios y
estados viejos hasta que su navegador revalide. En Vercel eso ya está resuelto por
`vercel.json` (`datos/` va con `Cache-Control: no-cache`); en otro hosting hay que
configurarlo a mano: en Netlify es un `_headers`, en Apache un `.htaccess`.

### Revisar antes de publicar

```bash
python -m pipeline.qa_overlay --proyecto "/ruta/a/Cauquenes_170926"
```

Deja en `salidas/<proyecto>/control-calce/` una imagen por vista con los polígonos
dibujados sobre la panorámica. Sirve para confirmar de un vistazo que todo cae donde
corresponde.

## La consola en línea

La consola corre local con `./consola.sh`, y la misma imagen se despliega en Cloud
Run para que el equipo la use desde cualquier parte:

```bash
gcloud builds submit --config=cloudbuild.yaml
```

No va en Vercel a propósito: **Vercel corta el cuerpo de cada petición en 4,5 MB** y
una panorámica pesa más de 60, y tampoco tiene disco donde escribir el sitio. Cloud
Run con `--use-http2` no tiene ese tope, aguanta una hora por petición y monta el
bucket de datos como volumen en `/datos`, así que el pipeline escribe igual que en
este computador.

Lo que hay que dejar puesto antes del primer despliegue:

| Qué | Dónde |
|---|---|
| Bucket de datos | `gs://tumasterplan-datos` en la misma región |
| `consola-secreto` | Secret Manager — con qué se firman las sesiones |
| `masterplan-bd` | Secret Manager — la Postgres de las cuentas. **Sin esto no arranca**: la carpeta de datos es un bucket montado y SQLite sobre GCS no tiene bloqueo de archivos, así que la base —con los correos y los hashes de clave— se corrompería |
| `vercel-token` | Secret Manager — para publicar los loteos ([vercel.com/account/tokens](https://vercel.com/account/tokens)) |
| `crm.csv` | en la carpeta de cada loteo que tenga export comercial |

**Entrar.** Una cuenta por persona: correo y contraseña con bcrypt, y una galleta
firmada con HMAC (`consola/acceso.py`, `consola/datos.py`). La galleta lleva solo el
id del usuario y la hora; el rol y de qué loteadora es se releen de la base en cada
petición, para que una cuenta desactivada, degradada o con la clave recién cambiada
pierda el acceso en la petición siguiente y no doce horas después. Sin
`CONSOLA_SECRETO` y fuera de este computador la consola **se niega a funcionar**:
sin secreto de firma, cualquiera se fabrica una galleta.

**Cada cliente ve lo suyo.** Las rutas no reciben un `cliente_id` que se pueda olvidar
de filtrar: reciben `registro.para(sesion)`, una vista que solo alcanza los loteos de
esa loteadora (`consola/proyectos.py`). Pedir uno ajeno da **404, no 403**: contestar
"existe pero no es tuyo" ya es contar algo. El inventario de rutas está declarado en
`consola/tests/test_app.py`, y una prueba lo compara con `app.routes` y **falla si
alguien agrega una ruta sin decir qué pasa cuando la pide otro cliente**.

**El dominio.** Hoy cada loteo queda en `masterplan-<slug>.vercel.app`. Con
`MASTERPLAN_DOMINIO=tumasterplan.cl` (la sustitución `_DOMINIO` del cloudbuild) la
consola pasa a mostrar `<slug>.tumasterplan.cl`; falta apuntar el dominio en Vercel,
una vez por loteo.

## El diseño

El sitio usa el sistema visual de Cierra, para que se sienta parte de la misma
familia: Plus Jakarta Sans (autoalojada en `web/vendor/fuentes/`, porque la CSP no
deja cargar de Google Fonts), superficies blancas sobre grises zinc, verde de marca
`#007c10`, radios de 6/8/12 px y sombras apenas insinuadas. Los tokens están en
`:root` de `web/css/estilos.css`.

La fotografía manda. Arriba va una barra fija con el nombre del loteo, la etapa como
"eyebrow" verde, el buscador y los filtros; el resto de la pantalla es la panorámica,
y el cromado —ficha, plano, leyenda, instrumentos— son tarjetas blancas con borde que
se apoyan encima sin taparla.

Cada parcela se marca con un contorno blanco fino y un disco numerado, que es el
objetivo de clic: un número redondo se acierta mucho mejor que el borde de un
polígono, sobre todo con el dedo. El estado lo lleva el disco, con los mismos tonos
que las pills de Cierra —verde disponible, ámbar reservado, azul vendido, oscuro no
disponible—; al ser un color sólido se lee igual sobre bosque, tierra o cielo. Se
definen en `pipeline/config.py` (`ESTADOS`), el sitio los lee del JSON, y la ficha,
la leyenda y los filtros los muestran como pills.

## El terreno

La proyección necesita saber a qué altura está el suelo bajo cada vértice. Asumirlo
plano funciona en un loteo llano y falla en una ladera: un lote 24 m más abajo que el
despegue, a 600 m del dron, se dibuja 60 m más lejos de donde está, y se nota contra
los caminos.

Por eso el pipeline baja un modelo de elevación (teselas Terrarium de AWS Open Data,
~8 m por píxel, sin llave) y proyecta cada vértice a su cota real. Las teselas quedan
en `.cache/terreno/`; sin red y sin caché avisa y sigue con terreno plano.

**El punto de despegue ancla todo.** El dron mide sus alturas respecto de donde
despegó, y su "altura absoluta" viene en un datum que no calza con el del DEM. Así
que el DEM aporta los desniveles y la cota del despegue la fija el dron: si el
despegue está mal ubicado, todos los lotes se corren juntos. Sin `despegue` en
`proyecto.json` se asume que el dron despegó bajo la primera toma, que es lo normal
pero no seguro: en Praderas de Cauquenes despegó bajo la última, y la diferencia
(16 m de cota) corría los lotes lejanos unos 40 m. La forma de comprobarlo es el
control de calce: los polígonos tienen que caer sobre los caminos.

## El calce fino

Con el sol y el terreno resueltos queda un residuo de ~0,5–1°: el nivelado de la
panorámica no es perfecto, el GPS del dron tiene unos metros de error y el DEM
también. Como el KMZ trae los caminos y los caminos de tierra se ven claros en la
foto, el pipeline ajusta por vista un giro, dos inclinaciones y un desnivel hasta que
las líneas del KMZ caen sobre los píxeles de camino. El ajuste queda en
`vistas.json` (`diagnostico.calibracion`); si no mejora el calce al menos un 3 % se
descarta, y `--sin-calibrar` lo apaga.

## El KMZ

Llega de dos formas y las dos sirven:

- **Polígonos**: un polígono por lote y, aparte, un punto con el nombre (`LOTE A123`).
  Es lo que exporta Global Mapper cuando el topógrafo ya cerró los lotes.
- **Red de líneas**: el dibujo CAD tal cual, donde cada arista es una línea suelta y
  hay un punto con el nombre dentro de cada lote. El pipeline cierra la red y se queda
  con las caras que tienen exactamente un nombre adentro; las demás (caminos, franjas
  de servidumbre, el recuadro de la leyenda) se descartan solas. Las divisorias que
  quedan a menos de 0,5 m del borde se pegan; un hueco mayor deja dos lotes fusionados
  en una sola cara, que aparece gris y sin nombre en el plano para que se note.

**Etapas.** Si el loteo tiene etapas, cada una repite la numeración desde 1 y el
dibujo las distingue por color. Para separarlas el KMZ necesita la leyenda: un
cuadrito de cada color junto a un rótulo `ETAPA 1`, `ETAPA 2`… (así viene de Global
Mapper). El id de cada lote queda como `etapa-número` (`2-7`) y el sitio lo muestra
como "Parcela 7 · Etapa 2". Sin leyenda, dos lotes con el mismo nombre cortan el
pipeline con un aviso: es un dato que falta, no algo que se pueda adivinar.

## La planilla

Los datos comerciales salen, en este orden, de:

1. **Un .xlsx en la carpeta del proyecto**, si lo hay.
2. **Un `crm.csv` en la carpeta del loteo**, o el que se pase con `--crm`, filtrado
   por la parcelación del proyecto: el nombre en mayúsculas o lo que diga
   `parcelacion` en `proyecto.json`. Las etapas del CRM (`PRADERAS DE CAUQUENES ET2`)
   calzan con las del KMZ; la parcelación sin sufijo es la etapa 1. En este
   computador, sin `crm.csv` propio se usa el export de `agente_reporteria`; si está
   desactualizado, corre antes su `refresh_data.sh`. **No hay ningún export global en
   la carpeta de datos**: con varios loteos, eso sería que quien no trae planilla
   hereda los precios de otro. Si el loteo no figura en el export, se avisa y las
   parcelas salen como no disponibles.
3. **Nada**: las parcelas salen como "No disponible".

La planilla puede ser .xlsx o .csv. Las columnas se detectan por nombre, sin
distinguir tildes ni mayúsculas. Reconoce:

| Columna | Obligatoria | Notas |
|---|---|---|
| `Parcela` | Sí | También se acepta `Lote`. Formatos: `A214`, `Lote A 420`, `LOTE 42`, `7-1` |
| `Parcelación` | No | Con sufijo `ET2` / `ETAPA 2` separa las etapas |
| `Estado` | No | `Disponible`, `Reservado`, `Vendido`, `No disponible`. Del CRM: `AGENDA`, `PRE-RESERVA` y `BORRADOR` cuentan como reservado; `ESCRITURA` y `ENTRADA CBR`, como vendido |
| `Superficie` | No | En m². Entiende `13.124` como 13.124 m² |
| `Servidumbre` | No | Ancho en metros |
| `Servidumbre m2` | No | Superficie de la servidumbre (es lo que trae el CRM) |
| `Precio` | No | Si falta o es 0, la ficha dice "A consultar" |
| `Moneda` | No | `CLP` (por defecto) o `UF` |
| `Link de pago` | No | Puede ser distinto por parcela |

Para agregar precios basta con sumar una columna `Precio` al xlsx. No hay que tocar
código.

## Estructura

**En el repo no está `salidas/`**: es lo que produce el pipeline, no código. La
primera vez hay que correrlo para tener un sitio.

```
tumasterplan/
├── pipeline/          Python: lee las fuentes y produce los datos
│   ├── config.py      Rutas, colores, umbrales; descubre las fuentes y el proyecto
│   ├── solar.py       Posición del sol y detección del disco solar
│   ├── kmz.py         Lectura del KMZ: polígonos o red de líneas, etapas por color
│   ├── terreno.py     Modelo de elevación (teselas Terrarium) para seguir las laderas
│   ├── excel.py       Lectura de la planilla comercial (.xlsx o .csv)
│   ├── crm.py         La planilla desde el export del CRM
│   ├── panoramas.py   Pose de cada foto y resolución del rumbo
│   ├── proyeccion.py  Proyección de polígonos a coordenadas angulares
│   ├── imagenes.py    Niveles de imagen para la web
│   ├── construir.py   Orquestador
│   └── qa_overlay.py  Control de calce
├── consola.sh         Abre la consola en el navegador
├── publicar.sh        Sube a Vercel el sitio de un proyecto
├── consola/           La consola: subir, construir, revisar y publicar
│   ├── app.py         API
│   ├── proyectos.py   Qué loteos conoce y en qué estado están
│   ├── trabajos.py    Corre el pipeline y muestra su avance en vivo
│   ├── comandos.py    Qué le pide al pipeline
│   └── web/           La página
├── web/               El sitio (html, css, js): la plantilla de la que se copia cada salida
│   ├── js/            Visor WebGL, mapa, ficha, filtros
│   ├── vercel.json    Cabeceras (caché, CSP) que viajan con cada sitio
│   └── pruebas.html   Pruebas de humo en navegador
├── salidas/           Generado por el pipeline, un proyecto por carpeta
│   └── <proyecto>/
│       ├── sitio/         Se sube tal cual (html + datos/ + panoramas/)
│       └── control-calce/ Generado por qa_overlay (no se sube)
└── docs/diseno.md     Por qué está hecho así
```

## Pruebas

```bash
python -m pytest -q                      # pipeline + consola
node --test web/js/camara.test.js
```

Y las de navegador, con el servidor levantado: http://localhost:8000/pruebas.html

Las capas cubren cosas distintas. Las de Python validan la astronomía y la
geometría contra invariantes conocidas. Las de Node validan la matemática de cámara.
Las de navegador levantan la aplicación real y comprueban que el panorama se dibuja,
que los polígonos caen sobre la imagen, que las tipografías cargan y que los flujos
responden. Las de la consola levantan su API con un pipeline de mentira: prueban la
orquestación —qué se lanza, qué se muestra, qué no se deja hacer— sin construir un
loteo entero.

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

2. ~~**Terreno plano.**~~ Resuelto: la proyección usa un modelo de elevación. Ver
   [El terreno](#el-terreno).

3. **Sin precios.** La planilla no los trae y el link de pago es uno solo genérico
   para las 202 parcelas. Ver la tabla de columnas más arriba.

4. **Las fotos de POSICIÓN 03 están mal rotuladas.** El archivo "50 METROS" es de
   100 m y el "100 METROS" es de 300 m. El pipeline usa la altura del XMP, no el
   nombre, así que salen bien; pero conviene renombrarlas en el Drive.
