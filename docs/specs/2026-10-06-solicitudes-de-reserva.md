# Solicitudes de reserva

## El problema

El botón "Reservar parcela" lleva al link de pago del loteo (en Praderas, Getnet).
Lo que pase ahí no vuelve al Masterplan: nadie se entera de que alguien quiso
reservar, y dos personas pueden pagar la misma parcela mientras el inventario
(Cierra o la planilla) sigue diciendo "disponible".

## La solución

1. Al tocar "Reservar parcela", el comprador deja nombre, teléfono y correo.
2. El sitio publicado se los manda a la consola (`POST /api/publico/reservas`).
   La consola revisa que el loteo esté publicado, que la parcela esté disponible en
   el sitio y que nadie la tenga apartada. Si todo calza:
   - guarda la solicitud;
   - **aparta la parcela por 2 horas**;
   - manda un correo a la dueña y al equipo de la loteadora;
   - y contesta con el link de pago, con `?parcela=<id>`, al que el visor lleva al comprador.
3. El visor pide las parcelas apartadas (`GET /api/publico/apartadas`) y las muestra
   como "Reserva en proceso", sin botón de reservar.
4. En la consola, la sección **Reservas** lista las solicitudes del loteo. Cada una
   se puede **confirmar** (queda apartada hasta que el inventario diga "Reservado")
   o **liberar** (vuelve a disponible). Una pendiente sin confirmar vence sola a las 2 horas.

La confirmación del pago es a mano. Que Getnet la avise sola necesita su API (Web
Checkout) con credenciales de comercio: queda para después.

## Decisiones

- **Plazo del apartado: 2 horas**, elegido por el usuario el 2026-10-06.
- **Estados:** `pendiente`, `confirmada` y `liberada` se guardan. *Vencida* no se
  guarda: es una pendiente cuyo plazo pasó.
- **Aviso por correo** con la infraestructura de `consola/cuentas.py`. En producción
  necesita `SENDGRID_API_KEY` y `EMAIL_FROM`. Sin ellos, la solicitud igual queda en
  la consola y el correo va al registro.
- **El inventario manda.** El apartado no cambia `parcelas.json` ni toca Cierra ni la
  planilla. Solo agrega una capa encima en el visor. Cuando el inventario marca la
  parcela, el apartado deja de importar.

## Seguridad

- **Rutas públicas sin sesión:** solo esas dos, con tope de frecuencia por IP: 5
  solicitudes por hora y 120 consultas de apartadas por minuto. El origen tiene que
  ser el sitio publicado de ese loteo (su URL guardada o `masterplan-<slug>.vercel.app`).
  En local se acepta `localhost`.
- **Validación:** nombre (2–120 caracteres), teléfono (8 a 15 dígitos), correo con
  forma de correo y parcela que exista en el sitio. Hay un campo trampa invisible
  contra robots. Los textos pasan por `limpiar_texto` antes de ir a un correo.
- **Aislamiento:** los datos del comprador solo los ve la loteadora dueña del loteo;
  las rutas de la consola contestan 404 a otra loteadora. Nunca van a git.
- **Contra el bloqueo de un loteo** (alguien que aparta todo con datos inventados):
  - máximo 10 solicitudes pendientes por loteo;
  - una pendiente por correo o teléfono;
  - cuerpo de hasta 4 KB;
  - revisar y apartar es un solo paso con candado, así dos pedidos simultáneos no
    apartan la misma parcela.
- El correo avisa que los datos los escribió el comprador, sin verificar.
- **Política de seguridad del sitio publicado:** `web/vercel.json` agrega a
  `connect-src` el dominio de la consola, porque hoy el visor no puede hablar con ella.

### Pendiente

- **Captcha** (Cloudflare Turnstile, validado en el servidor): el origen no frena a un
  robot, que puede inventarlo. Necesita una cuenta y sus claves.
- **Retención de datos personales** (Ley 19.628 y Ley 21.719): purgar o anonimizar las
  solicitudes liberadas y vencidas después de un plazo, y avisar en el formulario para
  qué se usan los datos.
- **Si se pone un proxy o CDN delante de Cloud Run**, revisar `ip_de`, que hoy toma el
  último `X-Forwarded-For`.

## Entrega

1. Consola: tabla, rutas públicas, apartado, correo y la API de la sección Reservas (este PR).
2. Visor: formulario y "Reserva en proceso".
3. Consola: la pantalla de la sección Reservas.
