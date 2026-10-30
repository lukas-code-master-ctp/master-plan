# Los trabajos en Cloud Run Jobs y la consola por petición

## Por qué

En octubre de 2026 Google Cloud pasó de ~CLP 3.500 a ~CLP 177.000 al mes. Casi todo es
el SKU "Services CPU (Instance-based billing)" de Cloud Run. La consola iba con:

- `--no-cpu-throttling`: con la CPU siempre asignada, Google cobra cada segundo que la
  instancia está prendida, atienda o no.
- `--cpu=2 --memory=8Gi`: el tamaño que pide construir un loteo con panorámicas.
- Cloud Scheduler llamando a `/api/tareas/cierra` cada 15 minutos: más o menos lo que
  Cloud Run espera antes de apagar una instancia sin uso. Nunca se apagaba.

Una instancia de 2 vCPU y 8 GiB prendida todo el mes en São Paulo cuesta unos CLP
140.000 a 150.000.

`--no-cpu-throttling` estaba porque la construcción corría en un hilo de fondo de la
consola. Con la CPU solo durante las peticiones, ese hilo se arrastraba al cerrar la
pestaña.

## Qué cambia

- La consola pasa a facturación por petición (`--cpu-throttling`) y 4 GiB. Sin visitas
  no cobra.
- Cada trabajo (construir, digitalizar el plano, publicar, actualizar el visor) corre en
  un Cloud Run Job: `tumasterplan-construir` (2 vCPU, 8 GiB) para los pesados y
  `tumasterplan-publicar` (1 vCPU, 2 GiB) para los livianos. Se paga solo mientras corre.
- El estado del trabajo pasa de la memoria del proceso a la tabla `trabajos`:
  `TrabajosRemotos` (`consola/trabajos_remotos.py`) tiene la misma cara que `Trabajos`,
  así que las rutas no cambian.
- `python -m consola.obrero <id>` corre el trabajo con el mismo `Trabajos` de siempre y
  copia el avance y un latido a la base cada 3 segundos.
- El `al_terminar` viaja como descriptor (`_con_cierre`) y el obrero lo vuelve a armar
  (`cierre_desde`): aplicar el diseño, anotar la publicación o cerrar la lectura del plano.
- Un trabajo sin latido por 3 minutos, o en cola por 10, se da por caído y suelta el loteo.
- Los correos salen dentro de la petición: un hilo que sigue después de responder se
  queda sin CPU.
- Republicar al arrancar lanza los jobs y no espera. Cada job anota lo suyo.

En el computador, en las pruebas y en el QA local nada cambia: sin
`CONSOLA_TRABAJOS=cloudrun` siguen corriendo en la consola.

## Ahorro esperado

Cloud Run pasa de ~CLP 150.000 al mes a unos pocos miles: las visitas a la consola y un
par de minutos de máquina por construcción (una construcción de 10 minutos con 2 vCPU y
8 GiB cuesta ~CLP 100). Lo fijo sigue: el balanceador (~US$18), Cloud SQL y Cloud Build.

## Antes del primer despliegue

La cuenta de servicio de la consola necesita `roles/run.developer` para encender los jobs
con el id como argumento. Si falta, el trabajo queda fallido con "no pude encender la
máquina del trabajo: HTTP Error 403" y la consola sigue funcionando.

## Lo que queda

- `--max-instances=1` sigue por los topes por IP de las rutas públicas, que viven en
  memoria.
- Un trabajo arranca 10 a 30 segundos más tarde que antes, lo que tarda Google en
  encender la máquina. La pantalla muestra "Encendiendo la máquina…".
