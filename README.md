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

Abre http://localhost:8780 en el navegador. En **Mis planos → Nuevo master** le pones
nombre, subes el KMZ, las panorámicas y, si la hay, la planilla de precios, y
aprietas **Construir**. En el detalle del loteo ves la portada, las cifras y el
control de calce, completas los datos (WhatsApp, referencias…) y recién entonces
**Publicar**. Corre en este computador a propósito: una carpeta de
panorámicas pesa unos 200 MB y no tiene sentido subirlas a otro lado para
procesarlas acá al lado. Si la carpeta ya está en el disco, en "usar una carpeta que
ya está en este computador" se registra sin copiar nada.

La primera vez el script crea la cuenta de casa e **imprime por pantalla una clave
provisional**. Anótala y cámbiala al entrar: no se vuelve a mostrar.

### Dejarla siempre encendida (hoy no se puede acá)

`com.ctp.tumasterplan.plist` la deja corriendo como servicio de macOS, igual que la
sincronización de notaría. **Pero no funciona con el proyecto dentro de `~/Desktop`**:
macOS protege Escritorio, Documentos y Descargas, y un agente de `launchd` no hereda
el permiso que sí tiene la Terminal. Falla con `Operation not permitted` antes de
arrancar —probado— y fallaría igual al leer las carpetas de vuelo, que también están
en el Escritorio.

Para habilitarlo hay que mover el proyecto y las carpetas de vuelo fuera de
`~/Desktop` (por ejemplo a `~/tumasterplan`), y entonces:

```bash
cp com.ctp.tumasterplan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ctp.tumasterplan.plist
launchctl kickstart -k gui/$UID/com.ctp.tumasterplan   # reiniciar tras cambiar código
tail -f logs/consola.log                                # ver qué está haciendo
```

La alternativa —dar "Acceso a disco completo" a `/bin/bash`— funciona pero se lo da a
todo lo que corra bash, que es mucho más de lo que hace falta.

Mientras tanto, `./consola.sh` desde la Terminal hace lo mismo con un comando.

Todo lo que hace la consola se puede hacer a mano, y es lo que sigue.

### Lo que necesita un loteo

Una carpeta con:

1. **Un KMZ** del loteo. Sirven los dos formatos que exporta Global Mapper: polígonos
   con un punto por lote (`LOTE A123`), o el dibujo CAD tal cual, como red de líneas
   con un punto por lote. Ver [El KMZ](#el-kmz). Si no lo tienes, sale del plano
   aprobado con [Crea tu KMZ](#crea-tu-kmz).
2. **Las panorámicas del dron**, equirectangulares y con el XMP intacto. Da lo mismo
   en qué subcarpetas vengan o si la misma foto está dos veces: las tomas se agrupan
   por GPS y se numeran en orden de captura.
3. **`proyecto.json`** con el nombre del loteo (opcional; sin él se usa el nombre de la
   carpeta). Es lo mismo que editan los datos del loteo en la consola:

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

## La landing

`landing/` es la página pública de tumasterplan.cl: un HTML, la tipografía y cuatro
imágenes, ~540 KB en escritorio y **sin una línea de JavaScript** (la CSP la sirve con
`script-src 'none'`). El hero sale de la panorámica de Cauquenes, reproyectada a
perspectiva con el mismo cálculo gnomónico que usa el visor.

Las capturas de `producto*.webp` son del visor real, tomadas con Chrome headless y
`--use-angle=swiftshader` —sin eso no hay WebGL y la panorámica sale negra—. Se
regeneran apuntando a un sitio construido; llevan un WhatsApp de ejemplo porque el
botón de contacto solo se dibuja cuando el loteo tiene número.

No está publicada todavía: faltan el correo y el WhatsApp de verdad. El propio pie de
la página lo dice, para que no se publique por descuido.

```bash
./publicar.sh landing tumasterplan --crear     # cuando estén los datos de contacto
```

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
| Cloud SQL `tumasterplan-bd` | Postgres 16 en la misma región; Cloud Run la alcanza por el socket `/cloudsql/…` (`--add-cloudsql-instances`) |
| `masterplan-bd` | Secret Manager — la Postgres de las cuentas, `postgresql+psycopg://<usuario>:<clave>@/<base>?host=/cloudsql/<proyecto>:southamerica-east1:tumasterplan-bd`. **Sin esto no arranca**: la carpeta de datos es un bucket montado y SQLite sobre GCS no tiene bloqueo de archivos, así que la base —con los correos y los hashes de clave— se corrompería |
| `vercel-token` | Secret Manager — para publicar los loteos ([vercel.com/account/tokens](https://vercel.com/account/tokens)) |
| `crm.csv` | en la carpeta de cada loteo que tenga export comercial |

**Entrar.** Una cuenta por persona: correo y contraseña con bcrypt, y una galleta
firmada con HMAC (`consola/acceso.py`, `consola/datos.py`). La galleta lleva solo el
id del usuario y la hora; el rol y de qué loteadora es se releen de la base en cada
petición, para que una cuenta desactivada, degradada o con la clave recién cambiada
pierda el acceso en la petición siguiente y no doce horas después. Sin
`CONSOLA_SECRETO` y fuera de este computador la consola **se niega a funcionar**:
sin secreto de firma, cualquiera se fabrica una galleta.

**Quién crea los loteos, y dónde se cobra.** Una loteadora se crea sus masters sola
(`POST /api/proyectos`), y nacen **sin pagar**: puede subir, construir y revisar
cuantas veces quiera. El cobro se controla en un solo lugar, **al publicar**, que es
cuando el loteo empieza a servirle a alguien más que a quien lo armó: publicar uno
sin pago da 402. El equipo lo deja publicar anotando el pago
(`/api/plataforma/proyectos/<slug>/pago`, solo rol `plataforma`), o habilita de
entrada un loteo ya pagado a nombre de una loteadora cuando el vuelo lo hace el
equipo. En los dos casos la nota de cobro es obligatoria —sin pasarela, esa línea de
texto es todo el control de pago que hay— y queda en el historial con quién la
escribió. Concentrar el control en un punto es lo que evita repartirlo por cada ruta
que escribe algo, que es como se termina con un cliente trabajando gratis sin que
nadie se entere.

**Cuentas propias.** Cualquiera se registra en `/registro` (su loteadora, su nombre,
correo y contraseña) o entra con Google. Quien se registra con correo confirma que es
suyo con un enlace (y un botón) antes de poder entrar: sin eso, cualquiera registraría
el correo de otro con una clave propia. Si el dueño de ese correo entra después con
Google, la clave que puso el otro se anula. "¿Olvidaste tu
contraseña?" manda un enlace de un solo uso que vence en 1 hora, y cambiarla corta las
sesiones abiertas. Registrarse con un correo que ya existe y pedir un enlace para uno
que no existe muestran lo mismo en pantalla: la diferencia llega solo al buzón. De los
tokens se guarda el hash. Registrarse y pedir enlaces tiene un tope de 5 por hora por IP.

| Variable | Para qué | Sin ella |
| --- | --- | --- |
| `SENDGRID_API_KEY` | Enviar los correos (el mismo proveedor que los reportes de CTP) | En este computador el correo queda en el registro de la consola. Desplegada, **Regístrate y "¿Olvidaste tu contraseña?" se cierran**: la entrada manda a escribirle al equipo, que crea las cuentas y da claves nuevas desde Loteadoras |
| `EMAIL_FROM` | Remitente, verificado en SendGrid | `no-responder@tumasterplan.cl` |
| `CONSOLA_URL` | La dirección pública de la consola, para los enlaces de los correos y la vuelta de Google (sin SendGrid ni Google no se usa) | La de la petición (detrás de Cloud Run llega como `http`) |
| `CIERRA_API_URL` | "Conectar con Cierra" en el inventario de cada loteo (ver [La planilla](#la-planilla)) | No se ofrece |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | "Continuar con Google" (cliente OAuth web; URI de redirección `<CONSOLA_URL>/entrar/google/vuelta`) | El botón no aparece |

Con Google, una cuenta existente se enlaza si Google dice que el correo está verificado;
alguien nuevo elige el nombre de su loteadora y entra.
Sin SendGrid, Google sigue abriendo cuentas nuevas (el correo ya viene verificado): la
entrada ofrece "¿No tienes cuenta? Créala con Google", y Regístrate y "¿Olvidaste tu
contraseña?" mandan a Google o a escribirle al equipo.

En Cloud Run, `CONSOLA_URL` y `GOOGLE_CLIENT_ID` salen de las sustituciones
`_CONSOLA_URL` y `_GOOGLE_CLIENT_ID` del cloudbuild, y `GOOGLE_CLIENT_SECRET` del secreto
`google-client-secret`. **Ese secreto tiene que existir antes del despliegue** (aunque
sea con un valor cualquiera): si falta, `gcloud run deploy` falla. Al cambiar de
dirección (por ejemplo a `app.tumasterplan.cl`), la nueva URI de redirección se agrega
también en el cliente OAuth de Google.

**Cuánto puede gastar una cuenta antes de pagar.** Como crear un master es gratis,
una loteadora tiene topes (`Limites` en `consola/proyectos.py`); el equipo no:

| Tope | Por defecto | Variable | Al pasarlo |
| --- | --- | --- | --- |
| Masters sin pagar a la vez | 3 | `CONSOLA_MAX_SIN_PAGAR` | 409 al crear |
| Tamaño de un loteo subido | 3072 MB | `CONSOLA_MAX_MEGAS_POR_LOTEO` | 413 al subir; la página avisa antes |
| Construcciones a la vez | 1 | `CONSOLA_MAX_CONSTRUCCIONES` | 429 al construir |

Quitar de la lista un master **subido y sin pagar** borra también su vuelo y lo
construido: si no, quitar y volver a crear sería la forma de llenar el disco igual.
Una carpeta vinculada o un loteo pagado conservan sus archivos.

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

## Despliegue continuo

Cada merge a `main` despliega la consola solo: un trigger de Cloud Build
(`consola-main`, región `southamerica-east1`, proyecto `tumasterplan`) corre el mismo
`cloudbuild.yaml`. El `gcloud builds submit` a mano sigue sirviendo.

**Los loteos también se ponen al día.** Cada sitio publicado lleva su propia copia del
visor, hecha al construirlo: un arreglo mergeado no llega a ningún loteo hasta que se
vuelve a subir. Con `CONSOLA_REPUBLICAR_AL_ARRANCAR=1` (solo lo pone el cloudbuild), la
consola calcula al arrancar la huella de `web/` y republica, de a uno y sin `--crear`,
los loteos publicados, pagados y construidos cuyo `visor_publicado` no coincide: copia
`web/` sobre el sitio ya construido, reescribe el diseño y corre `publicar.sh`
(`consola/republicar.py`). Un arranque en frío sin cambios en el visor no hace nada.
**No** reconstruye datos ni imágenes, y **no** publica un loteo que nunca se publicó.
Publicar a mano también lleva el visor actual. Para copiarlo sobre un sitio sin
publicar: `python -m pipeline.visor --sitio "salidas/<proyecto>/sitio"`.

**Cómo verlo.** No hay pantalla: queda en Cloud Logging, en líneas que empiezan con
`[republicar]`.

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="tumasterplan-consola"
  AND textPayload:"[republicar]"' --project tumasterplan --limit 50 --freshness 1d
```

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

### La marca de cada loteadora (Mis diseños)

Una loteadora puede publicar con su propia marca. Un diseño es un color, un logo,
una tipografía y los textos de los dos botones de la ficha. Se arma en **Mis diseños**
de la consola, con una vista previa, y se elige al crear el master o en su detalle.

- **Color:** de uno solo se deriva la escala `--marca-*` del cromado
  (`web/js/marca.js`). Si es muy claro para llevar texto blanco, el tono del botón se
  oscurece hasta llegar a 4,5:1. Los colores de estado no cambian: el verde de
  "disponible" significa lo mismo en todos los sitios.
- **Logo:** PNG, JPG, WebP o SVG de hasta 512 KB, en lugar de la brújula. Un SVG que
  traiga código o enlaces externos se rechaza.
- **Tipografía:** Plus Jakarta Sans, una serif clásica o la del sistema. Ninguna se
  baja de afuera.
- **Textos:** el del botón de contacto y el de pago; vacíos, los de siempre.

El diseño no pasa por el pipeline. La consola lo escribe en `sitio/datos/diseno.json`
(y el logo al lado) al terminar de construir y al publicar, así que cambiarlo solo
pide volver a publicar. Sin ese archivo el visor se ve como siempre. La vista previa
de la consola usa el mismo `marca.js` que el sitio publicado.

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

## Crea tu KMZ

Muchas loteadoras no tienen el KMZ de la subdivisión, y pedirle el DWG al topógrafo no
es una opción. Lo que sí tienen siempre es el **plano aprobado por el SAG y archivado en
el CBR**: un PDF escaneado (o una foto del papel), sin vectores ni coordenadas. Crea tu
KMZ convierte ese plano en el KMZ de la subdivisión, desde la consola y sin tocar
archivos.

Es una herramienta aparte, **Mis KMZ**: el KMZ no necesita un master. La loteadora
puede quererlo para su topógrafo, para Google Earth o para otro sistema, y usarlo en un
master cuando quiera (o nunca).

- **Dónde se entra.** La pestaña **Mis KMZ** (`#/kmz`), con su botón **Nuevo KMZ** y
  los KMZ en curso y terminados: el
  paso en que va cada uno, cuántos lotes tiene y la fecha. Nuevo KMZ pide un nombre y
  lleva a los 7 pasos (`#/kmz/<slug>`).
- **Al terminar**, **Descargar** entrega el `.kmz` con el nombre que le pusiste, y
  **Usar en un master** lo pone en uno existente o en un "Nuevo master con este KMZ".
  También se elige desde el otro lado: en *Nuevo master* el KMZ se sube o se elige de
  Mis KMZ, y en el detalle del master está "Usar un KMZ de Mis KMZ".
- **Quién ve qué**: como con los masters y los diseños, cada loteadora ve los suyos y el
  equipo los ve todos. Uno ajeno da 404, aunque se sepa su slug.
- **Gratis y sin tope de cantidad**, pero cada loteadora corre **una digitalización o
  una construcción a la vez**: cuentan juntas, porque cada una usa hasta ~5 min de CPU.

El flujo de antes, dentro del master ("No tengo el KMZ" en Nuevo master y el botón del
detalle, con las rutas `/api/proyectos/{slug}/plano/*`), **se retiró**. Construir sin
KMZ da 409: "falta el KMZ: súbelo o elige uno de Mis KMZ".

Specs: [`docs/specs/2026-10-01-crea-tu-kmz.md`](docs/specs/2026-10-01-crea-tu-kmz.md)
(el lector y la geometría) y
[`docs/specs/2026-10-02-kmz-independiente.md`](docs/specs/2026-10-02-kmz-independiente.md)
(Mis KMZ) y
[`docs/specs/2026-10-02-kmz-lotes-y-lector.md`](docs/specs/2026-10-02-kmz-lotes-y-lector.md)
(lotes sin número, números como en el plano, cuadro de superficies y el lector por teselas).
Resultados: [lectura de rótulos](docs/specs/2026-10-01-crea-tu-kmz-rotulos.md) y
[set de regresión](docs/specs/2026-10-01-crea-tu-kmz-regresion.md).

### El flujo

1. **Subir el plano** (PDF). De cada página se saca la imagen embebida **sin
   rerasterizar**; si no hay, se renderiza a 200 dpi. Se elige la página y la rotación.
2. **Marcar el dibujo**: un rectángulo alrededor de la situación propuesta, y máscaras
   sobre lo que no es dibujo (cuadros, cajetín, timbres, croquis). Si es una foto, las 4
   esquinas del marco impreso, para enderezar la perspectiva. Con la herramienta
   **Cuadro de superficies** se encierra el cuadro de áreas del plano, **aunque quede
   fuera del dibujo** (en Caminos de Rapel lo estaba, y no se leía): de ahí salen las
   áreas oficiales y la lista de números que el plano debería tener.
3. **Leer el plano** (por dentro, `digitalizar`), en un trabajo de fondo con avance en vivo: la tinta de los deslindes
   (roja o negra; se descartan verde, azul, achurados y cuadrícula), regiones cerradas
   separadas con los rótulos, una red de deslindes compartida entre vecinos, aristas
   enderezadas y los polígonos desde las caras. Sin traslapes ni huecos por
   construcción, y el deslinde va por el eje del camino: no hay polígonos de camino.
4. **Numerar**: el lector propone los números; la loteadora corrige o completa con un
   clic sobre el lote, y sus clics mandan. Se destacan los lotes sin número y los
   repetidos. Ver abajo *Los números de lote*.
5. **Ubicar en el mapa**, plano y mapa Esri lado a lado. Ver abajo.
6. **Revisar**: los lotes sobre la imagen satelital, coloreados por error de área contra
   el cuadro de superficies del plano, si se pudo leer (el marcado o, si no, el que se
   encuentre dentro del dibujo): verde ±2 %, ámbar ±5 %, rojo más. Sin cuadro, la
   pantalla sugiere marcarlo o revisar a ojo que los lotes calcen con los caminos.
7. **Crear el KMZ.** Si quedan lotes sin número, pide confirmación: esos lotes no van
   al KMZ, y lo normal es volver a Numerar.

Todo se puede retomar y rehacer: cambiar una entrada vuelve a calcular solo lo que
depende de ella (`huellas.json` dice qué quedó atrasado). Si un lote sale mal se
corrige con las entradas (una máscara, un número), no moviendo vértices.

### Los números de lote

- **Como en el plano.** El número se guarda tal cual está impreso: "LOTE 8-01" queda
  `8-01` (con el sector), y "LOTE 10-6", `10-6`. Antes el lector se quedaba con el último
  número y el KMZ decía "LOTE 1". Para comparar con un inventario o buscar repetidos se
  normaliza (`normalizar_id`): "8-01" y "8-1" son el mismo lote, así que no rompe las
  planillas que ya existían.
- **Un lote sin número no se pega al vecino.** Una región cerrada sin número de al menos
  el 40 % de la mediana de los lotes con número (`LOTE_FRAC` en `particion.py`) queda
  como **lote sin número**, en rojo, para numerarla con un clic. Solo se unen al vecino
  los trocitos (franjas, restos de texto: ≤ 0,36 de la mediana en el set). La excepción
  es un lote que su propio rótulo partió en dos (El Arrayán): se unen si el rótulo está
  encima del corte (a ≤ 1,5 mm del límite común) y el corte cae entero junto a él. En
  Caminos de Rapel, antes, los lotes 3, 5, 11 y 16 se pegaban sin aviso a sus vecinos.
- **Sugerencias.** Un número que leyó una sola pasada del lector no se asigna solo
  (`lector_apoyo_min`, 2), pero se ofrece: **"¿8-03? Confirmar"**, y un clic lo pone en
  su lote.
- **Números que faltan.** Si la serie de un sector salta (1, 2, 4, 6…), se avisa qué
  números faltan. Con el cuadro de superficies leído, los esperados salen del cuadro
  (así aparece también el último, el 16). Sin cuadro, un salto se avisa solo si el
  número anterior o el siguiente es vecino de un lote sin número; si no, suele ser un
  lote que esa lámina no dibuja (Curicó mostraba 10 avisos así; ahora ninguno).

### Ubicar: cuadrícula o anclas

La forma sale bien; **lo que mete error es la ubicación**. En las pruebas, con
cuadrícula impresa el centroide quedó a 1,7 m del real; con anclas de Google Earth,
a 5–10 m.

- **Cuadrícula impresa (preferida).** Si el plano trae marcas UTM (E-…, N-…), se leen,
  se descartan las que no siguen la progresión y se ajusta con las intersecciones.
  WGS84/SIRGAS UTM por defecto; PSAD56 si las anclas lo indican.
- **Anclas.** Pares de puntos plano ↔ mapa, con zoom grande sobre el plano: esquinas
  del predio y cruces de caminos. Se ajusta una similitud (escala, giro y traslación)
  por mínimos cuadrados, con el residuo de cada ancla. **Conviene marcar 4**: con 2 no
  hay cómo saber cuál está mala, y con 3 o más un ancla atípica (sin ella, su residuo
  pasa de 3× la mediana de las demás y de 4 m) queda marcada para quitarla o volver a
  marcarla. Cada ancla de Google Earth se desvía 1–19 m.
- **Ajuste fino**: un arrastre de los lotes sobre la imagen satelital, para calzar los
  caminos con los deslindes.

El huso UTM sale de las anclas o de la cuadrícula: no queda fijo en 19S.

**Aviso de escala.** Si hay al menos 3 lotes con área oficial, se compara la escala
que dan las anclas con la que implican las áreas del cuadro. Si difieren en más de
**1,5 %** (3 % en área), Ubicar lo avisa: las anclas de Google Earth pueden encoger o
agrandar el plano. En Caminos de Rapel lo encogían ~2,8 %, y eso explicaba buena parte
de que los lotes midieran 5–10 % menos que el oficial (el resto era texto pegado a un
deslinde que se tomaba por achurado: ahora solo cuentan como achurado las zonas de
250 mm² o más). Lo que corrige es marcar mejor las anclas, más separadas.

### El lector de rótulos

Tesseract (`tesseract-ocr` en la imagen, `pipeline/plano/rotulos.py`), con parámetros
globales: hasta 24 ángulos × 2 escalas × gris/Otsu (96 pasadas). Lee también las
marcas de la cuadrícula y el cuadro de superficies.

Para que quepa en 4 GiB y termine:

- **Por teselas.** Cada pasada lee la imagen en trozos de **hasta 14 Mpx**, ya
  agrandada y girada, con solapamiento para no cortar rótulos. Las pasadas a la vez se
  calculan con ese tamaño, no con el de la página. La caída de producción (una página de
  5008×7038 px con texto de 15 px, que se agranda 1,6× y crece otra vez al girar) era
  de memoria.
- **Primero la orientación.** Un sondeo a 0°, 45°, 90°… (gris y Otsu) dice en qué
  ángulos están los rótulos, y solo se leen esos: de 96 pasadas se baja a **26–46**
  en el set. Si el sondeo no encuentra la orientación, se leen todas.
- **Medido** con `--memory=4g --cpus=2`: el lector es **3 a 7 veces más rápido**; en la
  página que reproduce la caída, la digitalización completa bajó de 697 s a 307 s y el
  proceso queda en **~1,3 GiB** mientras lee. Ninguno de los 6 planos del set perdió
  lecturas.

Si el trabajo desaparece (el servidor se reinició o se cayó y el trabajo vivía en
memoria), la pantalla ya no se queda pegada en "30 de 96": muestra **"La digitalización
se interrumpió. Vuelve a intentarlo"** y habilita reintentar. Un 404 del trabajo lo da
por interrumpido de inmediato; los errores de red o 502/503/504 se reintentan y, al
quinto seguido, también.

**Rinde bien con rótulos grandes** (`LOTE 12`, también rotados o en diagonal: 97–98 %
de los lotes en Puente Negro e Hidango) y **mal con texto chico en cursiva o en foto**
(36 % en El Arrayán, 11 % en Curicó). Por eso el camino normal es leer y corregir: en un
plano así, la loteadora numera a clic. Sin Tesseract en el servidor, digitalizar sigue
con los números marcados a mano. Un número que solo una pasada leyó no cuenta
(`lector_apoyo_min`, 2 por defecto).

### Lo que se guarda

Cada KMZ tiene nombre (único por loteadora) y slug (único en todo el sistema) en la
tabla `kmzs`, y su carpeta en `/datos/kmz/<slug>/`:

| Archivo | Qué es |
|---|---|
| `plano.pdf` | El PDF tal como llegó |
| `paginas/<n>.jpg`, `<n>_mini.jpg` | Cada página sin rotar, y su miniatura |
| `entradas.json` | Lo que marca la loteadora: página, rotación, rectángulos, esquinas, números, anclas, cuadrícula, ajuste fino |
| `digitalizado.json` | Los lotes en píxeles, los rótulos leídos, la cuadrícula y las áreas oficiales |
| `georreferencia.json` | La transformación, el residuo de cada ancla y el datum |
| `lotes.geojson` | Los lotes en lon/lat, para el mapa |
| `huellas.json` | Con qué entradas se hizo cada paso |
| `<slug>.kmz` | El resultado. Que exista es lo que dice que el KMZ está terminado |

El KMZ es un Polygon por lote, con nombre `LOTE <n>` (el número como está en el plano o como
lo escribió la loteadora: `LOTE 8-01`; "8-01" y "8-1" se comparan como el mismo lote), KML 2.2 y sin líneas, así que
`pipeline/kmz.py` lo lee en modo polígonos. Borrar un KMZ borra su carpeta.

### Las rutas

Todas bajo `/api/kmz`, y declaradas en el inventario de `consola/tests/test_app.py`:

| Ruta | Qué hace |
|---|---|
| `GET /api/kmz`, `POST /api/kmz {nombre}` | Lista y crea |
| `GET /api/kmz/{slug}` | El estado: el paso que sigue, qué quedó atrasado y el último trabajo |
| `PATCH /api/kmz/{slug} {nombre}`, `DELETE /api/kmz/{slug}` | Renombra; borra con su carpeta |
| `POST /api/kmz/{slug}/plano` | Sube el PDF y saca las páginas |
| `GET /api/kmz/{slug}/paginas/{n}` | La imagen de una página (`?mini=1`, la miniatura) |
| `PUT /api/kmz/{slug}/entradas` | Guarda lo que marca la loteadora |
| `POST /api/kmz/{slug}/digitalizar` | Trabajo de fondo, clave `kmz:<slug>` (no choca con el slug de un master) |
| `POST /api/kmz/{slug}/georreferenciar` | Cuadrícula o anclas → UTM |
| `GET /api/kmz/{slug}/lotes` | Los lotes en píxeles o en lon/lat (`?en=lonlat`) |
| `POST /api/kmz/{slug}/crear` | Escribe `<slug>.kmz` |
| `GET /api/kmz/{slug}/descargar` | El `.kmz`, con el nombre en el `Content-Disposition` |

Lo que reescribe el plano o el KMZ, o lo borra, da 409 mientras se digitaliza.

**Usarlo en un master**: `POST /api/proyectos/{slug}/kmz {kmz: <slug del KMZ>,
confirmar_reemplazo}` copia el KMZ a las fuentes del master como `subdivision.kmz`,
donde lo busca construir. Solo KMZ propios y terminados. Si el master ya tenía un KMZ,
responde 409 con `existentes`; al confirmar, cada anterior queda como
`<nombre>.kmz.anterior` (se guarda solo el último reemplazado). Se escribe aparte y se
mueve al final: si algo falla a mitad, lo apartado vuelve a su nombre y el master queda
con el KMZ que tenía. Tampoco se cambia mientras el master construye o publica.

### Límites

- Hasta **12 páginas** por PDF y **200 megapíxeles** por página.
- La imagen de trabajo se reduce a **8 px/mm** (entre 6 y 8). Un A0 a 300 dpi son
  ~140 MP: sin el tope pasaba de 4 GiB; con él, el pico queda en ~2 GiB de RAM. La
  exactitud casi no cambia con la resolución.
- En Cloud Run (4 GiB, 2 vCPU) digitalizar corre como subproceso en un trabajo de
  fondo, igual que construir, y una digitalización o construcción a la vez por
  loteadora. La geometría toma
  menos de un minuto; el lector es lo que pesa: corre tantas pasadas a la vez como
  núcleos tenga el contenedor (`LECTOR_HEBRAS` lo acota) y las que quepan en la
  memoria libre. Medido en la imagen con `--cpus=2 --memory=4g`: Puente Negro con
  lector toma ~4,6 min (3,6 de ellos, el lector) y el proceso llega a ~2,1 GiB
(antes de las teselas, el plano grande de producción se caía).
  `--no-cpu-throttling` del cloudbuild es lo que deja avanzar el trabajo con la
  pestaña cerrada; `--timeout` no aplica, porque no hay petición abierta.

### El set de regresión

Los planos de prueba con sus KMZ reales viven en `regresion/planos/<plano>/`
(`plano.pdf`, `real.kmz`, `entradas.json`), **fuera de git**: traen nombres y RUT de
propietarios. Hay que pedirlos aparte; sin la carpeta, las pruebas que la usan se saltan.
Son 6: Algarrobo, Caminos de Rapel (el sexto, 16 lotes "8-01"…"8-16", del QA del
2026-10-02), Curicó, El Arrayán, Hidango y Puente Negro. Los números se emparejan con
el real normalizados ("8-01" calza con "Lote 8-01").

```bash
python -m pipeline.plano.regresion                 # los 6 planos, ~1 min
python -m pipeline.plano.regresion --plano curico
python -m pipeline.plano.regresion --actualizar-linea-base
```

Corre digitalizar → georreferenciar → kmz y mide contra el KMZ real: IoU por lote,
centroide y Hausdorff, tal cual y con la similitud óptima ("what-if", que separa la
forma de la ubicación), error de área, traslapes y huecos. Compara con
`regresion/linea_base.json` y **sale con 1** si un plano empeora más que la tolerancia
(IoU what-if −0,01, centroide what-if +0,25 m, o menos lotes). La línea base solo
cambia con `--actualizar-linea-base`. Esta corrida usa los números marcados a mano y
el lector apagado, así que no necesita Tesseract.

`--con-lector` borra los números a mano y enciende el lector: mide cuánto numera solo.
Es informativa (no se compara con la línea base) y necesita Tesseract, o sea, la imagen
de Docker:

```bash
docker build -t masterplan360 .
docker run --rm -v "$PWD/regresion:/app/regresion" masterplan360 \
  python -m pipeline.plano.regresion --con-lector
```

La tabla de `--con-lector` (en `regresion/resultados_con_lector.json`) dice, por plano:
rótulos leídos, lotes (y cuántos de lote sin número), numeración correcta contra el real,
errados, IoU y centroide, cuántas áreas del cuadro se leyeron y el error de área contra
ellas, y los segundos del lector. La última corrida, al cerrar la tarea 4:

| Plano | Lotes + sin número | Numeración correcta | Segundos (lector) |
|---|---|---|---|
| Puente Negro | 65 + 0 | 65 / 65 (100 %) | 275 (215) |
| Hidango | 56 + 2 | 56 / 58 (97 %) | 177 (137) |
| Algarrobo | 75 + 0 | 67 / 76 (88 %) | 265 (241) |
| Caminos de Rapel | 12 + 4 | 12 / 16 (75 %) | 14 (14) |
| El Arrayán | 58 + 52 | 52 / 183 (28 %) | 96 (84) |
| Curicó | 14 + 13 | 8 / 87 (9 %) | 77 (57) |

En Rapel, los 4 que el lector no lee ya no se pierden: salen sin número y en rojo, y el
cuadro trae sus 16 áreas.

**Correr las pruebas en Windows.** Con Smart App Control, las pruebas de la consola
pueden no importar la DLL compilada de SQLAlchemy. Se corre la suite completa en
Docker, con el código montado de solo lectura:

```bash
docker build -t masterplan360 .
MSYS_NO_PATHCONV=1 docker run --rm -u root -w /app \
  -v "$(pwd -W)/consola:/app/consola:ro" -v "$(pwd -W)/pipeline:/app/pipeline:ro" \
  -v "$(pwd -W)/web:/app/web:ro" -v "$(pwd -W)/publicar.sh:/app/publicar.sh:ro" \
  masterplan360 sh -c "pip install -q pytest httpx && python -m pytest -q -p no:cacheprovider"
```

(`pwd -W` y `MSYS_NO_PATHCONV=1` son de Git Bash; en Linux o macOS basta `$PWD`.)

Ojo: El Arrayán se ajustó mirando su KMZ real, así que el set ya es de desarrollo. Lo
que dice cómo le irá al método con un plano nuevo es la primera corrida de ese plano:
conviene sumar al set cada plano nuevo con KMZ real y anotar esa corrida antes de
ajustar nada con él.

### A mano

```bash
python -m pipeline.plano digitalizar <carpeta-del-plano>       # entradas.json → digitalizado.json
python -m pipeline.plano georreferenciar <carpeta-del-plano>   # → georreferencia.json, lotes.geojson
python -m pipeline.plano kmz <carpeta-del-plano> <destino.kmz>
```

El formato de `entradas.json` está en `pipeline/plano/digitalizar.py`.

## La planilla

Los datos comerciales salen, en este orden, de:

1. **La planilla del proyecto.** Primero el inventario subido desde la consola
   (`inventario.xlsx` o `inventario.csv`, que reemplaza al anterior aunque cambie de
   formato); si no hay, el primer .xlsx de la carpeta del vuelo.
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
| `Proyecto` (o `Parcelación`) | No | El nombre del loteo; con sufijo `ET2` / `ETAPA 2` separa las etapas, como en Cierra |
| `Etapa` | No | La etapa en su propia columna (`2`, `ET2` o `Etapa 2`); manda sobre el sufijo |
| `Estado` | No | `Disponible`, `Reservado`, `Vendido`, `No disponible`. Del CRM: `AGENDA`, `PRE-RESERVA` y `BORRADOR` cuentan como reservado; `ESCRITURA` y `ENTRADA CBR`, como vendido. De Cierra: `EN_PROCESO` es reservado; `INSCRITA` y `PROMESA`, vendido |
| `Superficie` | No | En m². Entiende `13.124` como 13.124 m² |
| `Servidumbre` | No | Ancho en metros |
| `Servidumbre m2` | No | Superficie de la servidumbre (es lo que trae el CRM) |
| `Precio` | No | Si falta o es 0, la ficha dice "A consultar" |
| `Moneda` | No | `CLP` (por defecto) o `UF` |
| `Link de pago` | No | Puede ser distinto por parcela |
| `Rol` (o `Rol de avalúo`) | No | Texto, como `8073-145`. La ficha lo muestra en una tarjeta |
| `Topografía` | No | Texto corto: `Plana`, `Plana y lomaje`. La ficha lo muestra en una tarjeta |
| `Pie` | No | En la moneda del precio. `20%` se calcula sobre el precio. La ficha dice el monto y el porcentaje |
| `Cuotas` | No | Cuántas cuotas (también `N° cuotas`) |
| `Valor cuota` | No | En la moneda del precio. No se calcula: sin la tasa sería inventar |
| `Reserva` | No | Monto en pesos; el botón de pago dice "Reservar parcela ($250.000)" |

Las seis últimas son opcionales y la ficha no deja huecos: lo que no viene, no aparece. Las
parcelas que llegan desde Cierra no las traen. Un cero cuenta como celda vacía.

Una planilla que repite una parcela se rechaza con un mensaje: casi siempre son etapas que
numeran desde 1 sin decir cuál es cuál, y quedarse con una fila publicaría el precio de otra
parcela. El export del CRM sí trae duplicados de vez en cuando, y ahí se toma la última.

Para agregar precios basta con sumar una columna `Precio` al xlsx. No hay que tocar
código.

**Conectar con Cierra.** Si la loteadora lleva sus parcelas en Cierra, no llena
planillas: crea en Cierra una clave de API con permiso `parcelas:read` (Admin →
Integraciones), la pega una vez en la consola, y en cada loteo elige los proyectos de
Cierra que lo alimentan —en Cierra cada etapa es un proyecto aparte, así que dice qué
etapa del plano es cada uno—. La consola trae las parcelas (`GET
/integrations/proyectos` y `GET /integrations/parcelas` de la API de Cierra) y las
escribe como `inventario.csv` en la carpeta del loteo: el pipeline no sabe que Cierra
existe. Construir un loteo conectado trae lo último antes de lanzar; si Cierra no
contesta, se construye igual con el último inventario y se avisa. "Actualizar desde
Cierra" lo trae sin generar las imágenes de nuevo. La clave se guarda cifrada con una
llave derivada de `CONSOLA_SECRETO` (cambiar ese secreto obliga a pegarla de nuevo) y
es siempre la de la loteadora dueña del loteo, aunque quien conecte sea el equipo.
Todo esto aparece solo con `CIERRA_API_URL` (en producción, `https://api.cierra.cl`).

**La plantilla.** La consola entrega el .xlsx listo para llenar (`consola/plantilla.py`):
en Nuevo master sale con tres filas de ejemplo, y en el detalle de un master construido,
con una fila por parcela del KMZ y lo que muestra hoy, que es lo que evita escribir un lote
distinto del dibujo. Trae listas para Estado y Moneda y la columna Parcela como texto, para
que Excel no convierta `2-7` en una fecha. Subir el inventario desde el detalle reconstruye
el loteo sin volver a generar las imágenes.

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
│   ├── visor.py       Copia el visor (web/) sobre un sitio y calcula su huella
│   ├── construir.py   Orquestador
│   ├── qa_overlay.py  Control de calce
│   └── plano/         Crea tu KMZ: del plano escaneado a los lotes
│       ├── __main__.py      CLI: digitalizar, georreferenciar, kmz
│       ├── pagina.py        Imagen de cada página, rotación, recorte, perspectiva, 8 px/mm
│       ├── tinta.py         Máscara de deslindes (roja o negra)
│       ├── particion.py     Regiones, red de deslindes y polígonos sin traslapes
│       ├── rotulos.py       Lector de rótulos, cuadrícula y cuadro (Tesseract)
│       ├── digitalizar.py   entradas.json → digitalizado.json
│       ├── georreferencia.py  Cuadrícula o anclas → UTM, con residuo por ancla
│       ├── salida.py        El KMZ: un Polygon por lote
│       ├── metricas.py      IoU, centroide y Hausdorff contra un KMZ real
│       └── regresion.py     El set de regresión
├── consola.sh         Abre la consola en el navegador
├── publicar.sh        Sube a Vercel el sitio de un proyecto
├── consola/           La consola: subir, construir, revisar y publicar
│   ├── app.py         API
│   ├── proyectos.py   Qué loteos conoce y en qué estado están
│   ├── trabajos.py    Corre el pipeline y muestra su avance en vivo
│   ├── comandos.py    Qué le pide al pipeline
│   ├── plano.py       Crea tu KMZ: un plano en su carpeta y lo que sale de él
│   ├── kmzs.py        Mis KMZ: el KMZ de la loteadora, sin master, y quién ve cuál
│   ├── republicar.py  Al arrancar, republica los loteos con el visor atrasado
│   └── web/           La página
│       ├── js/kmzs.js     Mis KMZ: la lista, el nombre y "usar en un master"
│       └── js/kmz.js, kmz_geometria.js, lienzo_plano.js, mapa_kmz.js   Los 7 pasos de un KMZ
├── web/               El sitio (html, css, js): la plantilla de la que se copia cada salida
│   ├── js/            Visor WebGL, mapa, ficha, filtros
│   ├── vercel.json    Cabeceras (caché, CSP) que viajan con cada sitio
│   └── pruebas.html   Pruebas de humo en navegador
├── salidas/           Generado por el pipeline, un proyecto por carpeta
│   └── <proyecto>/
│       ├── sitio/         Se sube tal cual (html + datos/ + panoramas/)
│       └── control-calce/ Generado por qa_overlay (no se sube)
├── regresion/         Planos y KMZ reales de Crea tu KMZ (fuera de git: nombres y RUT)
└── docs/diseno.md     Por qué está hecho así
```

## Pruebas

```bash
python -m pytest -q                      # pipeline + consola
node --test web/js/*.test.js consola/web/*.test.js
python -m pipeline.plano.regresion       # Crea tu KMZ, si tienes la carpeta regresion/
```

Las pruebas del lector de rótulos necesitan Tesseract y se saltan sin él (en Windows,
por ejemplo). Se corren en la imagen; `httpx2` es solo para el cliente de prueba de
Starlette, que la imagen no trae:

```bash
docker run --rm -u root masterplan360 sh -c "pip install -q httpx2 && python -m pytest -q pipeline/tests/test_plano_*.py consola/tests/test_plano.py"
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

## QA local

La consola de punta a punta en este computador, con cuentas y loteos de prueba y
reemplazos locales de Cierra, Vercel y el correo. No toca nada de afuera:

```bash
npm run qa:levantar     # consola + Cierra falsa + hosting falso, con datos sembrados
npm run qa:captura      # capturas con Playwright (-- --como duenio --ruta '#/planos')
npm run qa:correos      # lo que la consola "mandó" por correo, con sus enlaces
npm run qa:bajar
```

Cuentas, servicios, recetas y problemas comunes en [docs/qa-local.md](docs/qa-local.md).

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
