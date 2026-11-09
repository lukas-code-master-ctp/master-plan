# Interesados y estadísticas del sitio

Fecha: 9 de noviembre de 2026. Viene del análisis de La Nube 360 y Latitud 360: los dos
le dan a la loteadora una forma de saber quién pregunta y qué se mira. Tu Masterplan
tenía WhatsApp y Reservar, pero nada para quien todavía no está listo para pagar, y la
loteadora no sabía qué parcelas atraían gente.

## Qué se agrega

1. **"Me interesa esta parcela"** en la ficha del visor, para parcelas en venta y solo
   si el sitio sabe a qué consola pedir (`consola` y `loteo` en `parcelas.json`, igual
   que la reserva). Abre un formulario corto: nombre, teléfono, correo opcional y cuándo
   prefiere que lo llamen. No aparta la parcela ni lleva a pagar.
2. **Interesados** en la consola: una pestaña con la lista de todos los loteos, filtros
   por loteo y por estado, y a la derecha el elegido con WhatsApp, llamar, estado,
   responsable y nota. Se baja como planilla (CSV con punto y coma y BOM, que Excel en
   español abre bien).
3. **Estadísticas del sitio** en el detalle de un loteo publicado: visitas, fichas
   abiertas, clics en WhatsApp y en Reservar, interesados y solicitudes de reserva, en
   7, 30 o 90 días, con un gráfico de visitas (por día; por semana en 90 días) y la tabla
   de las parcelas más miradas.

## Decisiones

- **El responsable es texto libre.** Muchas loteadoras venden con corredores que no
  tienen cuenta en la consola; amarrarlo a un usuario los dejaría fuera. La consola
  sugiere los nombres ya usados para que no se escriba "María" de tres formas.
- **Un estado por interesado, sin historial propio.** Los cambios de estado quedan en la
  actividad de la loteadora (Configuración → Actividad) con quién los hizo, sin los datos
  del comprador, porque ese historial lo ve todo el equipo.
- **Repetidos.** El mismo teléfono por la misma parcela dentro de 24 horas no crea otro
  interesado ni manda otro correo: es alguien que apretó dos veces o volvió.
- **Cifras, no personas.** Los eventos se guardan sumados por día (hora de Chile),
  parcela y tipo, sin IP ni identificador. El visor cuenta una visita y cada ficha una
  vez por sesión del navegador (`sessionStorage`); los clics cuentan todos. Así "parcelas
  abiertas" se acerca a "personas que la miraron" sin rastrear a nadie.
- **Nadie llena la tabla con basura.** Un evento de una parcela que no está en el
  `parcelas.json` publicado se descarta, hay un tope de 30 eventos por pedido y de 60
  pedidos por minuto por IP, y solo se acepta el origen del sitio del loteo.
- **Los interesados y las reservas se cuentan desde sus tablas**, no como eventos: son
  datos que ya existen y no se pueden inflar desde afuera.
- **Sin build y sin librería de gráficos.** El gráfico es una grilla de barras en HTML y
  CSS, con la cifra de cada barra al pasar o enfocar.
- **Fuera: el precio en UF convertido a pesos.** Estaba en la maqueta y se dejó fuera a
  pedido de Eduardo.

## Rutas

| Ruta | Sesión | Qué hace |
| --- | --- | --- |
| `POST /api/publico/interesados` | No | Deja un interesado. 201; 400 con el motivo; 404 si la parcela no existe; 403 de otro origen; 429 sobre 5 por hora por IP |
| `POST /api/publico/eventos` | No | Suma eventos. 204; 400 si la lista no tiene forma; 429 sobre 60 por minuto por IP |
| `GET /api/proyectos/{slug}/interesados` | Sí | Los 500 más recientes del loteo. Otra loteadora: 404 |
| `PATCH /api/proyectos/{slug}/interesados/{id}` | Sí | Estado, responsable o nota. Otra loteadora: 404 |
| `GET /api/proyectos/{slug}/estadisticas?dias=7\|30\|90` | Sí | El resumen. Otra loteadora: 404 |

Las públicas reciben el cuerpo como texto plano, como la reserva, para que el navegador
no pida permiso antes con un OPTIONS.

## Tablas

- `interesados`: proyecto, parcela, nombre, teléfono, correo, horario, estado,
  responsable, nota, creado y actualizado.
- `estadisticas`: proyecto, día, parcela ("" para una visita), tipo y cantidad, única por
  (proyecto, día, parcela, tipo).

Son tablas nuevas: las crea `create_all` al arrancar, sin migración. Al borrar un loteo se
borran con él.
