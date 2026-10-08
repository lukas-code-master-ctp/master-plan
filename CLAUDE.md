# Tu Masterplan

Visor aéreo de loteos (panorámicas 360 del dron con las parcelas proyectadas encima)
y la consola donde las loteadoras suben, construyen, revisan y publican sus masters.
El detalle de todo está en `README.md` y el porqué en `docs/diseno.md`; esto es lo
mínimo para trabajar sin leerlos enteros.

## Las piezas

| Carpeta | Qué es |
| --- | --- |
| `pipeline/` | Python. KMZ + panorámicas + planilla → sitio estático en `salidas/<slug>/sitio/`. `python -m pipeline.construir --proyecto <carpeta>`. Parámetros en `pipeline/config.py`. `pipeline/plano/` es Crea tu KMZ (PDF del plano → KMZ). |
| `web/` | El visor (HTML/JS sin build, WebGL). Es la plantilla que se copia a cada sitio construido. |
| `consola/` | FastAPI servida con hypercorn (`./consola.sh`, puerto 8780). Página en `consola/web/`. Cuentas, loteos y pagos en SQLAlchemy. |
| `publicar.sh` | Sube un sitio a Vercel. La consola lo llama al publicar. |
| `landing/` | La página pública de tumasterplan.cl, sin JavaScript. |
| `qa/` | El QA local: siembra, servicios falsos y capturas. |

## La base de datos

- Local y en las pruebas: SQLite en `<MASTERPLAN_DATOS>/consola.db`.
- Desplegada (Cloud Run): Postgres en Cloud SQL vía `MASTERPLAN_BD`. Sin esa variable
  y con `CONSOLA_ENTORNO` distinto de `local`, la consola no arranca.
- No hay Alembic. Una columna nueva en una tabla existente se agrega en `_migrar()`
  de `consola/datos.py`, idempotente y compatible con SQLite y Postgres.

## Pruebas

```bash
pip install -r requirements.txt -r requirements-consola.txt httpx   # pytest viene en requirements.txt
npm test     # python3 -m pytest -q  &&  node --test web/js/*.test.js consola/web/*.test.js
```

La suite de Python tarda unos 3 minutos. Las pruebas del lector de rótulos se saltan
sin Tesseract, y eso es normal en los hilos.

Reglas que las pruebas hacen cumplir:

- **Rutas nuevas de la consola:** el inventario de rutas de `consola/tests/test_app.py`
  se compara con `app.routes`. Una ruta nueva tiene que declararse ahí, diciendo qué
  pasa cuando la pide otra loteadora.
- **Aislamiento entre loteadoras:** las rutas reciben `registro.para(sesion)`, nunca un
  `cliente_id` suelto. Un loteo ajeno responde 404, no 403.
- **El cobro se controla solo al publicar** (402 sin pago). No agregues chequeos de
  pago en otras rutas.

## QA local

Todo está en `docs/qa-local.md`. Lo esencial:

```bash
npm run qa:levantar                  # de cero: borra .qa/, siembra y levanta todo
npm run qa:levantar -- --conservar   # sobre el .qa/ existente, sin sembrar
npm run qa:captura                   # recorrido en escritorio y celular → .qa/capturas/
npm run qa:captura -- --como duenio --ruta '#/planos/praderas-demo' --movil
npm run qa:correos                   # lo que la consola "mandó" (buzón en .qa/buzon/)
npm run qa:bajar                     # termina los procesos; .qa/ queda
```

- Cuentas ficticias, todas con la clave `qa-clave-segura-1`: `plataforma@qa.test`
  (equipo CTP), `duenio@loteadora-demo.test`, `equipo@loteadora-demo.test`,
  `duenio@otra-loteadora.test` (otra loteadora, para aislamiento) y
  `sinconfirmar@qa.test` (no entra). En `qa:captura` se usan por alias: `plataforma`,
  `duenio`, `equipo`, `otra`, `sinconfirmar`, `anonimo`.
- Servicios falsos: SQLite en lugar de Postgres, buzón en carpeta en lugar de SendGrid,
  `qa/cierra_falsa.py` (clave `qa-cierra-clave-demo-0001`) y un `vercel` falso que
  publica en `http://127.0.0.1:8792/`. Google OAuth queda apagado.
- `source .qa/entorno.sh` para tener el mismo entorno en otro comando.
- Playwright es global y Chromium ya está instalado. No corras `playwright install`.
- Sin acceso a S3 no se construye nada (las teselas de elevación se bajan de verdad).
  El satélite del plano chico (Esri) no llega desde los hilos; ese error es esperable.

## Convenciones

- Todo en español: código, nombres, comentarios, commits y documentación. Los
  comentarios explican el porqué, no el qué.
- Commits con prefijo en minúscula (`feat:`, `fix:`, `docs:`, `refactor:`, `infra:`),
  y `(tarea N)` al final cuando vienen de un plan.
- Specs en `docs/specs/AAAA-MM-DD-<tema>.md` y planes en `docs/plans/AAAA-MM-DD-<tema>.md`.
- No hay build para el front: `web/` y `consola/web/` son JS de módulos servido tal cual.
- No van a git `salidas/`, `.qa/`, `*.db`, `regresion/` ni nada con datos reales de
  propietarios (nombres, RUT).

## PRs y despliegue

- **No hay staging.** Los PR van directo a `main`.
- Cada merge a `main` despliega la consola en Cloud Run (trigger `consola-main` de
  Cloud Build) y, al arrancar, republica los loteos publicados cuyo visor quedó
  atrasado (`consola/republicar.py`). Un cambio en `web/` llega a los sitios de los
  clientes con el merge.
- La landing (`landing/`) también sale con el merge: Vercel la publica en
  www.tumasterplan.cl apenas llega a `main`.
- Mergear, desplegar o tocar producción (Cloud SQL, el bucket, Vercel) necesita
  autorización explícita.
