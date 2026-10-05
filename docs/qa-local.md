# QA local

La consola corriendo en tu máquina, con cuentas y loteos de prueba y un reemplazo
local para cada servicio de afuera. Sirve para que un hilo en la nube (o una persona)
pruebe una pantalla de punta a punta sin staging, sin credenciales y sin tocar nada real.
El porqué y el diseño están en [`specs/2026-10-05-qa-local.md`](specs/2026-10-05-qa-local.md).

**Lo que no cubre:**

| Qué | Por qué |
| --- | --- |
| Entrar con Google | No hay un OAuth falso: sin `GOOGLE_CLIENT_ID` el botón no aparece. |
| Leer rótulos en Crea tu KMZ | Necesita Tesseract, que no está en los hilos. Los números a mano funcionan. |
| Cobros | No hay pasarela: "habilitar" es una marca que pone `plataforma` (Anotar pago). |
| El criterio visual final | Las capturas sirven para encontrar errores; la última mirada es en staging. |

## Inicio rápido

```bash
npm run qa:levantar                    # de cero: borra .qa/, siembra y levanta todo
npm run qa:levantar -- --conservar     # levanta sobre el .qa/ que ya había, sin sembrar
npm run qa:captura                     # el recorrido de siempre, escritorio y celular
npm run qa:correos                     # lo que la consola "mandó" por correo
npm run qa:bajar                       # termina los procesos; .qa/ queda
```

`qa:levantar` instala las dependencias de Python que falten, levanta la Cierra falsa y el
servidor de lo publicado, siembra (construye y publica Praderas Demo, unos segundos),
levanta la consola y termina imprimiendo URLs, cuentas y comandos. Los procesos quedan en
segundo plano. Si había algo arriba de una vez anterior, lo baja primero.

Todo vive en `.qa/` (fuera de git):

| Carpeta | Qué hay |
| --- | --- |
| `.qa/datos/` | `consola.db` (SQLite), loteos subidos, salidas, `cache/terreno` |
| `.qa/buzon/` | un JSON por correo enviado |
| `.qa/publicados/` | lo que "publicó" el `vercel` falso |
| `.qa/capturas/` | las capturas de `qa:captura` |
| `.qa/logs/` | `consola.log`, `cierra_falsa.log`, `publicados.log` |
| `.qa/pids/` | un `.pid` por proceso |
| `.qa/entorno.sh` | el entorno de la consola, para `source` |

## Cuentas

Todas con la clave **`qa-clave-segura-1`**. Entran sin cambiar la clave.

| Alias | Correo | Qué es |
| --- | --- | --- |
| `plataforma` | `plataforma@qa.test` | Equipo de CTP: ve todas las loteadoras y el back-office (menú de la cuenta → Loteadoras) |
| `duenio` | `duenio@loteadora-demo.test` | Dueña de "Loteadora Demo" |
| `equipo` | `equipo@loteadora-demo.test` | Equipo de "Loteadora Demo" |
| `otra` | `duenio@otra-loteadora.test` | Dueño de "Otra Loteadora", para probar aislamiento |
| `sinconfirmar` | `sinconfirmar@qa.test` | Se registró y no confirmó el correo: **no entra** |
| `anonimo` | — | Solo en `qa:captura`: no entra con ninguna cuenta |

## Datos sembrados

| Loteadora | Loteo (slug) | Cómo queda |
| --- | --- | --- |
| Loteadora Demo | Praderas Demo (`praderas-demo`) | Habilitado (pagado), KMZ sintético de 12 lotes en 2 etapas, planilla, panorámicas sintéticas, WhatsApp, diseño "Marca Demo", **construido y publicado** |
| Loteadora Demo | Loteo sin construir (`loteo-sin-construir`) | Sin pagar, con fuentes subidas, sin construir |
| Loteadora Demo | Loteo vacío (`loteo-vacio`) | Sin pagar, sin archivos |
| Otra Loteadora | Loteo ajeno (`loteo-ajeno`) | Sin pagar, sin archivos. `duenio` no lo ve |

Además, Loteadora Demo tiene el diseño "Marca Demo" y un KMZ vacío en Mis KMZ
("Plano de prueba"). La siembra corre solo con `qa:levantar` sin `--conservar`; si
Praderas Demo no se pudo construir o publicar, lo avisa con `⚠` y deja el resto sembrado.

## Servicios

| Servicio real | Reemplazo local | Dónde | Variable |
| --- | --- | --- | --- |
| Postgres (Cloud SQL) | SQLite | `.qa/datos/consola.db` | `MASTERPLAN_DATOS` |
| Bucket de datos | carpeta | `.qa/datos/` | `MASTERPLAN_DATOS` |
| La consola | hypercorn | `http://127.0.0.1:8780` | `QA_PUERTO_CONSOLA` |
| SendGrid | buzón en carpeta (`CorreoEnCarpeta`) | `.qa/buzon/` | `CONSOLA_BUZON`, `QA_BUZON` |
| Cierra (API de integraciones) | `qa/cierra_falsa.py` | `http://127.0.0.1:8791` | `QA_PUERTO_CIERRA` |
| Vercel (CLI) | `qa/bin/vercel`, primero en el `PATH` | `.qa/publicados/`, servido en `http://127.0.0.1:8792` | `QA_PUERTO_PUBLICADOS` |
| Google (OAuth) | apagado | — | — |
| Teselas de elevación (S3 público) | **ninguno: se bajan de verdad** | caché en `.qa/datos/cache/terreno/` | — |

Los puertos se cambian al levantar:

```bash
QA_PUERTO_CONSOLA=9780 QA_PUERTO_CIERRA=9791 QA_PUERTO_PUBLICADOS=9792 npm run qa:levantar
```

`qa:levantar` vacía antes las variables que podrían apuntar a algo real
(`MASTERPLAN_BD`, `SENDGRID_API_KEY`, `GOOGLE_CLIENT_*`, `VERCEL_TOKEN`, `CIERRA_API_URL`,
`CONSOLA_URL`...) y fija `CONSOLA_ENTORNO=local`. Deja todo eso en `.qa/entorno.sh`:

```bash
source .qa/entorno.sh          # mismo entorno en otra terminal o comando
which vercel                   # .../qa/bin/vercel, el falso
curl -s -H 'X-API-Key: qa-cierra-clave-demo-0001' "$CIERRA_API_URL/integrations/proyectos"
```

**Hazlo siempre si cambiaste los puertos**: `qa:captura` busca la consola en
`QA_URL_CONSOLA` o `QA_PUERTO_CONSOLA` y, sin ellos, en el 8780.

**Cierra falsa.** `GET /integrations/proyectos` y `GET /integrations/parcelas?proyecto_id=1,2`,
con la clave en `X-API-Key`. Solo acepta **`qa-cierra-clave-demo-0001`**; cualquier otra
da 401 (sirve para probar el error de clave). Trae "Praderas Demo Etapa 1" y "Etapa 2",
seis parcelas cada una, en los cuatro estados, con precios en CLP y UF.

**Vercel falso.** Imita `project add`, `link`, `deploy --prod` e `inspect`, lo justo para
que corra el `publicar.sh` de verdad. `project add` falla si el proyecto ya existe, como
el real. La URL que queda anotada en el loteo termina en `#.vercel.app`, por ejemplo
`http://127.0.0.1:8792/masterplan-praderas-demo/#.vercel.app`: `publicar.sh` solo
acepta alias `https://` o que terminen en `.vercel.app`, y el fragmento es la forma de
que acepte la URL local sin cambiar nada (el navegador no lo manda y el visor no lo lee).
Ábrela tal cual.

## Recetas

### Capturar una pantalla

```bash
npm run qa:captura -- --como duenio --ruta '#/planos'                      # escritorio, 1440×900
npm run qa:captura -- --como duenio --ruta '#/planos' --movil              # celular, 390×844
npm run qa:captura -- --como duenio --ruta '#/planos/praderas-demo' --pagina-completa
npm run qa:captura -- --como anonimo --ruta /registro --salida /tmp/registro.png
npm run qa:captura -- --como duenio --ruta '#/kmz' --esperar '#pantalla-kmzs'   # espera un selector (15 s)
```

| Opción | Qué hace |
| --- | --- |
| `--como <alias>` | `plataforma`, `duenio` (por defecto), `equipo`, `otra`, `sinconfirmar`, `anonimo` |
| `--ruta <ruta>` | `#/...` (pantalla de la consola), `/...` (página del servidor) o `http...` (URL completa) |
| `--movil` | 390×844, escala 2, táctil |
| `--esperar <selector>` | espera ese elemento; si no, espera a que la red quede quieta |
| `--salida <archivo.png>` | dónde guardarla; si no, `.qa/capturas/<alias>-<ruta>[-movil].png` |
| `--pagina-completa` | la página entera, no solo lo visible |

Imprime la ruta de la captura y, debajo, con `!`, los errores de consola del navegador,
errores de página y respuestas 4xx/5xx que vio. **Esos son hallazgos**: no cambian el
código de salida. Sale con 1 solo si no pudo abrir la consola o entrar.

Rutas útiles: `/entrar`, `/registro`, `/olvide`, `#/planos`, `#/planos/<slug>`, `#/kmz`,
`#/disenos`.

### El recorrido completo

```bash
npm run qa:captura                     # o con --pagina-completa
```

En escritorio y después en celular, en `.qa/capturas/`:

| Archivo | Cuenta | Qué |
| --- | --- | --- |
| `01-entrar[-movil].png` | anonimo | `/entrar` |
| `02-planos` | duenio | Mis planos |
| `03-praderas` | duenio | detalle de Praderas Demo |
| `04-kmz` | duenio | Mis KMZ |
| `05-disenos` | duenio | Diseños |
| `06-backoffice` | plataforma | el diálogo Loteadoras (`#avatar` → `#loteadoras`) |
| `07-publicado` | duenio | el sitio publicado de Praderas Demo |

Un paso que no aplica (Praderas no publicado, una cuenta que no entra) se salta y lo dice.

### Regístrate, siguiendo el enlace del buzón

```bash
source .qa/entorno.sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$QA_URL_CONSOLA/registro" \
  -d loteadora='Loteadora Nueva' -d nombre='Persona Nueva' \
  -d email=nueva@qa.test -d clave='una-clave-larga-1'
sleep 1                                # el correo se manda en segundo plano
npm run qa:correos                     # asunto, destinatario y enlaces
npm run qa:captura -- --como anonimo --ruta "$(npm run -s qa:correos -- --ultimo)"
```

El enlace es `.../verificar?t=...`: la página tiene un botón "Confirmar y entrar" (no
entra al abrir el enlace). Entrar como `sinconfirmar` (también desde `qa:captura`) le
reenvía ese correo. Para probar también el formulario, captura `/registro` o usa
un script (más abajo). `qa:correos -- --para <correo>` filtra por destinatario.

Usa `npm run -s` dentro de `$(...)`: sin `-s`, npm agrega su encabezado al enlace.
`--ultimo` sale con 1 si no hay correo o no trae enlace.

### Olvidé mi contraseña

```bash
curl -s -o /dev/null -X POST "$QA_URL_CONSOLA/olvide" -d email=duenio@loteadora-demo.test
sleep 1
npm run qa:captura -- --como anonimo --ruta "$(npm run -s qa:correos -- --ultimo)"
```

El enlace es `.../restablecer?t=...` (vence en 1 hora) con el formulario "Guardar y
entrar". Si cambias la clave de `duenio`, `qa:captura --como duenio` deja de entrar
hasta el próximo `qa:levantar` sin `--conservar`.

### Conectar Cierra y sincronizar

Como `duenio`, en Praderas Demo (`#/planos/praderas-demo`), sección Inventario:

1. **Conectar con Cierra** → pega `qa-cierra-clave-demo-0001` → **Seguir**.
2. Marca "Praderas Demo Etapa 1" y "Etapa 2" (la etapa viene sugerida) → **Conectar**.
3. Con el loteo conectado aparecen **Actualizar desde Cierra** y **Desconectar**.

Con otra clave, el diálogo muestra "Cierra no aceptó esa clave...". Lo que pidió la
consola queda en `.qa/logs/cierra_falsa.log`. Hay un script de ejemplo de estos pasos
más abajo.

### Construir "Loteo sin construir"

Como `duenio`, en `#/planos/loteo-sin-construir`, botón **Construir**. El avance aparece
en la misma pantalla ("Ver el registro"); termina con el control de calce. Baja teselas
de S3 la primera vez (ver Problemas). Captura cuando termine:

```bash
npm run qa:captura -- --como duenio --ruta '#/planos/loteo-sin-construir' \
  --esperar '#plano-calce:not([hidden])' --pagina-completa
```

`--esperar` espera hasta 15 s; para una construcción más larga, espera en un script
(ver el ejemplo) o repite la captura.

### Publicar y abrir el sitio publicado

Praderas Demo ya está publicado: su botón dice **Volver a publicar**. Publicar pide
confirmar con un `confirm()` del navegador. Un loteo sin pagar tiene Publicar apagado:
entra como `plataforma`, abre el loteo y usa **Anotar pago** → "Habilitar publicación".

```bash
ls .qa/publicados/                     # masterplan-praderas-demo/ ...
npm run qa:captura -- --como anonimo \
  --ruta 'http://127.0.0.1:8792/masterplan-praderas-demo/#.vercel.app'
npm run qa:captura -- --como anonimo --movil \
  --ruta 'http://127.0.0.1:8792/masterplan-praderas-demo/'
```

### Aislamiento entre loteadoras

```bash
npm run qa:captura -- --como otra --ruta '#/planos'                 # solo "Loteo ajeno"
npm run qa:captura -- --como otra --ruta '#/planos/praderas-demo'   # "Este loteo no existe"
npm run qa:captura -- --como duenio --ruta '#/planos'               # sin "Loteo ajeno"
```

La pantalla solo busca en la lista que le dio la API. Para probar la API misma, con la
sesión de `otra` en curl (un loteo ajeno tiene que dar 404):

```bash
source .qa/entorno.sh
curl -s -c /tmp/otra.galletas -o /dev/null -X POST "$QA_URL_CONSOLA/entrar" \
  -d email=duenio@otra-loteadora.test -d clave=qa-clave-segura-1
curl -s -b /tmp/otra.galletas -o /dev/null -w '%{http_code}\n' \
  "$QA_URL_CONSOLA/api/proyectos/praderas-demo/cierra"          # 404
curl -s -b /tmp/otra.galletas "$QA_URL_CONSOLA/api/proyectos"    # solo loteo-ajeno
```

### Ver los registros

```bash
tail -f .qa/logs/consola.log           # peticiones, errores, y cada correo con su texto
tail -n 50 .qa/logs/cierra_falsa.log   # una línea por petición a la Cierra falsa
tail -n 50 .qa/logs/publicados.log     # las peticiones al sitio publicado
```

## Pasos más largos que una captura

Para clics y formularios, un script de Playwright en Node. Usa el Playwright global de
la máquina, como `qa/captura.mjs` (`cargarPlaywright`), y entra igual que su `entrar()`.
Guárdalo fuera del repo (p. ej. en `/tmp`) y córrelo con `node`:

```js
// /tmp/cierra.mjs: conecta Praderas Demo con la Cierra falsa, como duenio.
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const raiz = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = createRequire(path.join(raiz, 'noop.js'))(path.join(raiz, 'playwright'));
const BASE = process.env.QA_URL_CONSOLA || 'http://127.0.0.1:8780';

const navegador = await chromium.launch();
const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 }, locale: 'es-CL' });
pagina.on('dialog', (d) => d.accept());   // los confirm() de Publicar, Quitar, Desconectar
pagina.on('pageerror', (e) => console.log('! página:', e.message));
pagina.on('console', (m) => m.type() === 'error' && console.log('! consola:', m.text()));

await pagina.goto(`${BASE}/entrar`);
await pagina.fill('input[name="email"]', 'duenio@loteadora-demo.test');
await pagina.fill('input[name="clave"]', 'qa-clave-segura-1');
await Promise.all([
  pagina.waitForURL((u) => u.pathname !== '/entrar'),
  pagina.click('form[action="/entrar"] [type="submit"]'),
]);

await pagina.goto(`${BASE}/#/planos/praderas-demo`);
await pagina.click('#inventario-cierra [data-accion="cierra-conectar"]');
await pagina.fill('#cierra-clave', 'qa-cierra-clave-demo-0001');
await pagina.click('#cierra-guardar-clave');
await pagina.waitForSelector('#cierra-lista li');
for (const marca of await pagina.locator('#cierra-lista input[type=checkbox]').all()) await marca.check();
await pagina.click('#cierra-listo');
await pagina.waitForSelector('[data-accion="cierra-actualizar"]:not([hidden])');

mkdirSync('.qa/capturas', { recursive: true });
await pagina.screenshot({ path: '.qa/capturas/cierra-conectado.png', fullPage: true });
console.log(await pagina.textContent('#cierra-estado'));
await navegador.close();
```

```bash
source .qa/entorno.sh && node /tmp/cierra.mjs
```

Piezas para otros pasos:

| Necesitas | Cómo |
| --- | --- |
| El slug o el estado de un loteo | `await (await pagina.request.get(BASE + '/api/proyectos')).json()` (usa la sesión de la página) |
| Construir | `pagina.click('#pantalla-plano [data-accion="construir"]')`, y esperar con `waitForSelector('#plano-calce:not([hidden])', { timeout: 600000 })` |
| Publicar | `pagina.click('[data-accion="publicar"]')` con el `on('dialog')` de arriba |
| Un mensaje de error | `#aviso` fuera de un diálogo; `dialog[open] .aviso` dentro de uno |
| El back-office | `pagina.click('#avatar')`, luego `pagina.click('#loteadoras')` → `dialog#clientes[open]` |

Si el paso es una captura más que quieres en cada recorrido, agrégalo a `RECORRIDO` en
`qa/captura.mjs`: cada paso tiene `nombre`, `alias`, `ruta` (función async que devuelve
la ruta o `{ salto: 'motivo' }`) y, opcionales, `antes` (async, recibe la página: clics
antes de la foto) y `esperarA` (selector).

## Problemas comunes

| Síntoma | Qué hacer |
| --- | --- |
| `✗ El puerto 8780 está ocupado` | Otra QA arriba: `npm run qa:bajar`. Si no es tuya, usa otros puertos (`QA_PUERTO_*=...`) y después `source .qa/entorno.sh` antes de `qa:captura`. |
| `✗ <proceso> se cayó al arrancar` | Mira la cola que imprime o `.qa/logs/<proceso>.log`. |
| Falta un módulo de Python | `qa:levantar` corre `pip install -r requirements.txt -r requirements-consola.txt` si falta alguno; sin red para pip, no hay arreglo local. |
| `No encontré Playwright` / `No pude abrir Chromium` | En los hilos Playwright es global (`npm root -g`) y Chromium está en `PLAYWRIGHT_BROWSERS_PATH`. Revisa esa variable. **No corras `playwright install`**: baja navegadores que no hacen falta y puede no tener red. |
| Praderas Demo "NO construido (falló)" o Construir falla al bajar el terreno | Las teselas se bajan de `s3.amazonaws.com/elevation-tiles-prod`. Sin red a S3 no se construye nada. La caché queda en `.qa/datos/cache/terreno/` y se pierde con cada `qa:levantar` sin `--conservar`: después de la primera vez, prefiere `--conservar`. |
| `qa:captura` no encuentra la consola | ¿Está arriba? `curl -s -o /dev/null -w '%{http_code}' $QA_URL_CONSOLA/entrar` debe dar 200. ¿Cambiaste puertos sin `source .qa/entorno.sh`? |
| `X no pudo entrar` | ¿Cambiaste su clave? Vuelve a sembrar con `npm run qa:levantar` (sin `--conservar`). `sinconfirmar` no entra a propósito. |
| Regístrate u Olvidé no mandan correo | Tope de 5 por IP y 3 por buzón por hora, en memoria: `qa:bajar` y `qa:levantar -- --conservar` lo reinician. Usa otro correo para registrar. |
| `--ultimo` trae un enlace viejo | El correo se manda en segundo plano: espera un segundo. Filtra con `--para`. |
| `--conservar` falla con "no hay .qa/datos" | La primera vez se levanta sin `--conservar`. |
