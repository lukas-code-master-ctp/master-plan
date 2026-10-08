# La lectura del plano se retoma si se cae la instancia

## El problema

El 2026-10-08 Lukas leyó Constitución ("conti") en Crea tu KMZ. A los 16 minutos, en la
pasada 42 de 96, la pantalla dijo "La lectura del plano se interrumpió (el servidor se
reinició)".

Logs de Cloud Run (`tumasterplan-consola`, revisados con el gcloud de Lukas):

- 14:01:08 UTC: `POST 202 /api/kmz/conti/digitalizar`.
- 14:17:21: último `GET 200 /api/trabajos/…`. 14:17:22: un 503 y después el primer 404, en
  una instancia nueva de la misma revisión ("Starting new instance. Reason: AUTOSCALING").
- No hubo despliegue (la última revisión era de las 13:12). Tampoco faltó memoria (p99 entre
  27 y 29 % de 8 GiB, sin "Memory limit"). Ni hubo inactividad (sondeo cada 0,7 s y la CPU
  al 100 %). La instancia murió sin señal ni mensaje, lo más probable por un reemplazo del
  host.

Medido en local con 2 núcleos, como Cloud Run: la hoja 1 de Constitución (El Arrayán, texto
de 7 px) da 60 teselas por pasada y ~33 s por pasada. Son 36 pasadas en 942 s, con un pico
de 1,3 GB. Rapel tarda 68 s. Cuando el sondeo no encuentra la orientación se leen las 96
pasadas: más de media hora.

La causa de fondo: el trabajo vive solo en la memoria del proceso. Cloud Run puede cambiar
la instancia cuando quiera, así que una lectura larga se pierde entera y reintentarla
empieza de cero.

## Lo decidido (Lukas, 2026-10-08)

1. **La consola retoma la lectura sola al arrancar**, aunque la pestaña esté cerrada. Lo
   intenta hasta 2 veces (3 intentos en total).
2. **Solo resistencia**: la velocidad (más vCPU, menos ángulos) queda como propuesta.
3. **Lo que se ve**: una línea en el detalle técnico ("Se retoma la lectura del plano donde
   quedó…") y el escáner sigue como si nada. No se agrega ningún aviso arriba.

## La solución

### Avance por pasada en el disco (pipeline)

- `rotulos.leer(…, avance_en=<carpeta>)`: cada pasada que termina entera (todas sus
  teselas, sin error) se escribe en `<carpeta>/<pasada>.json` (escritura atómica:
  temporal + `replace`). Al empezar, se cargan las pasadas que ya están y se saltan. El
  sondeo, `orientaciones` y la selección final usan las lecturas guardadas igual que las
  nuevas. Un archivo ilegible cuenta como no leído.
- El conteo "X de Y pasadas" incluye las retomadas, y se avisa una línea "Rótulos: se
  retoman N pasadas ya leídas".
- `digitalizar._leer_rotulos` usa `<carpeta del plano>/lector-avance/<huella_lector>/`.
  La huella ya cubre el PDF, la página, el rectángulo, las máscaras, la unión y
  `rotulos.VERSION`: si cambia algo de eso, no se reusa nada. Cuando `digitalizado.json`
  ya quedó escrito (con o sin Tesseract), se borra `lector-avance/` entera: si la instancia
  muere digitalizando los lotes, la lectura sigue retomable. Las carpetas de otras huellas
  se borran al empezar.
- La cuadrícula y el cuadro (menos de un minuto) no se guardan por partes.

### La consola recuerda qué lectura está corriendo

- Al lanzar una lectura (`POST /api/kmz/{slug}/digitalizar`) se escribe
  `<carpeta del KMZ>/lectura.json` con `{"intento": 1, "comenzo": …}`. Cuando el trabajo
  termina (listo o falló), se borra. Si la instancia muere, queda.
- Al arrancar, la consola revisa los KMZ de la base. Por cada uno con `lectura.json` y sin
  trabajo corriendo:
  - Si `intento < 3`: relanza la misma lectura con `intento + 1` (las mismas entradas y el
    mismo `al_terminar`). Su primera línea es "Se retoma la lectura del plano donde quedó
    (intento N de 3)."
  - Si no: borra `lectura.json` y no relanza. La pantalla muestra lo de hoy
    ("se interrumpió…").
- Esto pasa dentro del arranque (lifespan), antes de atender peticiones: el primer sondeo
  que llega a la instancia nueva ya ve el trabajo retomado. Siempre está prendido, también
  en local. Sin `lectura.json` no hace nada.
- Un KMZ borrado o con la carpeta incompleta (sin PDF o sin entradas válidas) se salta,
  borrando su `lectura.json`.

### La pantalla sigue al trabajo retomado

- Hoy, si el sondeo recibe 404, el trabajo se da por perdido. Ahora, cuando la clave es
  `kmz:<slug>`, antes se pide `GET /api/kmz/<slug>`: si trae un trabajo corriendo con otro
  id, se sigue ese, sin perder las líneas ya mostradas. Si no, queda como hoy.
- Mientras la instancia nueva arranca (502/503/504 o error de red) se aguanta ~1 minuto
  de reintentos, no ~10 s: la instancia del 2026-10-08 tardó 20 s en quedar lista.
- Al volver a la página con una lectura retomada, ya funciona: `GET /api/kmz/<slug>` trae el
  trabajo y la pantalla lo sigue.

## Fuera del alcance

- La velocidad de la lectura (propuestas en el informe: 4 vCPU, menos ángulos cuando el
  sondeo falla, tope al agrandado del texto de 7 px).
- Retomar construcciones y publicaciones de masters.
- Cloud Run Jobs o una cola externa.

## Riesgos

- Si la lectura misma mata la instancia, se reintenta 2 veces y para: no queda en un ciclo.
- Escribir ~100 archivos chicos por lectura en el bucket montado: cada uno pesa unos KB y
  se escribe una vez por pasada (cada 20–30 s).
- Con `--max-instances=1` hay una sola instancia, salvo durante un despliegue. Ahí la
  revisión nueva retoma una lectura que la vieja todavía corre (gasta un intento), hasta que
  la vieja recibe SIGTERM. Si la vieja termina primero, la nueva sigue escribiendo su avance
  sin caerse.
