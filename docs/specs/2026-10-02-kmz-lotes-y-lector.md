# Mis KMZ: lotes que no se pierden, números como en el plano y un lector que no se cae

## Problemas (QA del usuario, 2026-10-02)

**1. Caminos de Rapel (16 lotes de 5.000 m²).** El KMZ salió con 12 lotes. Medido contra el
real:
- Los lotes bien separados quedaron a 2–3 m (IoU 0,85–0,94).
- Faltan el 3, 5, 11 y 16. El lector no leyó esos números y la partición pegó esas regiones
  sin número a un vecino (`fusiones_sin_tinta`): dos al lote 2 (13.791 m²) y una a cada uno
  de los lotes 4 (8.674 m²) y 9 (9.361 m²). **No hubo ningún aviso.**
- El cuadro de superficies quedó fuera del rectángulo del dibujo y no se leyó (`cuadro: 0`).
  Sin él no hay control de área ni lista de números esperados.
- El plano dice "LOTE 8-01" y el KMZ dice "LOTE 1": el lector se queda con el último número.
- Los lotes correctos miden 4.500–4.770 m², un 5–10 % menos que el oficial.

**2. Plano grande (página de 5008×7038 px, texto típico de 15 px).** En producción la
instancia de Cloud Run se cayó a la pasada 30 de 96 del lector (12 s por pasada, CPU al
99 % por 5 min). El trabajo vivía en memoria, se perdió, y la pantalla quedó pegada en
"30 de 96". Lo más probable es la memoria: con texto de 15 px el lector agranda la imagen
1,6× (2,6× los píxeles), y al girarla en diagonal crece otra vez.

## Decisiones

- **Los números van como en el plano** ("8-01", "10-6"), con el par sector-lote completo. El
  pipeline del master ya los compara normalizados (`normalizar_id`: "8-01" = "8-1"), así que
  no rompe inventarios.

## Solución

1. **Números como en el plano.** El lector conserva el rótulo completo ("LOTE 8-01" → 8-01) y
   el KMZ lo nombra igual. Lo que escribe la loteadora se respeta tal cual.
2. **Nada del tamaño de un lote se pega a un vecino.** Una región sin número de área
   comparable a un lote (≥ ~40 % de la mediana de los lotes con número) queda como **lote sin
   número**, en rojo, para numerarla con un clic. Solo se siguen pegando los trocitos (franjas,
   restos de texto).
3. **Huecos en la numeración.** Si aparecen 1, 2, 4, 6… 15 (por sector), se avisa "faltan el
   3, 5 y 11". Con el cuadro leído, los esperados salen del cuadro (incluido el 16).
   Sin cuadro, un hueco de la serie se avisa solo si el lote anterior o el siguiente toca
   una cara sin número del tamaño de un lote: si no, suele ser un lote que esa lámina no
   dibuja (Curicó mostraba 10 huecos así; ahora ninguno, y Rapel sigue con 8-03, 8-05, 8-11).
4. **Marcar el cuadro de superficies.** Una herramienta en el paso Marcar para encerrarlo,
   aunque esté fuera del dibujo. Se lee con los números y las áreas oficiales, y alimenta los
   faltantes y el color por error de área.
5. **Un lector que cabe y termina.**
   - Lee **por trozos** de tamaño acotado (con solapamiento para no cortar rótulos). Las
     hebras se calculan contando el agrandado y el giro.
   - Primero detecta en qué orientaciones están los rótulos y solo lee esas (de 96 a ~20–30
     pasadas).
   - Se mide con el plano grande en un contenedor de 4 GiB / 2 vCPU.
6. **La pantalla no se queda pegada.** Si el trabajo desaparece (el servidor se reinició), se
   dice "La digitalización se interrumpió. Vuelve a intentarlo" y se habilita reintentar.
7. **El área de menos.** Se mide con Caminos de Rapel en el set de regresión si viene de la
   escala de las anclas o del reparto de la franja de camino, y se corrige lo que sea del
   método.

## Aceptación

- Caminos de Rapel (sexto plano del set, fuera de git) con sus entradas reales: **16 lotes**
  con números "8-01"…"8-16". Si el lector no lee alguno, ese lote sale **sin número y en
  rojo**, no pegado a otro. Se avisan los faltantes.
- El plano grande digitaliza con el lector en 4 GiB / 2 vCPU sin caerse, en un tiempo razonable
  (objetivo < 8 min).
- La regresión de los otros planos no empeora más que la tolerancia.
- `pytest` y `node --test` sin fallas nuevas.
