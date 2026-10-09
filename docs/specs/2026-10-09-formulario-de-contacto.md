# Formulario de contacto en la landing

## Qué

La landing (tumasterplan.cl) tiene un formulario para pedir el precio de un plan o hablar de
Enterprise. Reemplaza los botones que abrían el correo: mucha gente no tiene un programa de
correo configurado en el navegador y el contacto se perdía.

## Decisiones

- **Lo recibe la consola**, no un servicio externo (Formspree y similares): los datos de los
  interesados quedan en casa. Lo eligió el usuario (2026-10-09).
- **Sin JavaScript.** La landing funciona sin scripts (el único es Analytics). El formulario
  es un `<form method="post">` común; la consola contesta con una redirección `303` a la
  landing, a `#contacto-enviado` o `#contacto-error`, y la landing muestra el aviso con
  `:target`.
- **Solo la landing puede enviarlo**: si llega un `Origin` que no es tumasterplan.cl (o
  localhost en local), 403. La redirección vuelve siempre a la landing, nunca a una
  dirección que traiga la petición.
- **Anti-abuso igual que las reservas**: 5 envíos por hora por IP, cuerpo de 16 KB como
  máximo, campo trampa `sitio` (se contesta "enviado" sin guardar) y validación de cada
  campo. Obligatorios solo el nombre y el correo.
- **Lo ve solo el equipo de CTP**, en la pestaña Contactos de la consola: quien escribe todavía
  no es una loteadora. Las rutas cuelgan de `/api/plataforma/` y a una loteadora le contestan
  403.
- **Aviso por correo** a cada cuenta de plataforma activa y confirmada. En producción no hay
  SendGrid configurado: el correo no sale, pero el mensaje queda en Contactos igual.
- **Analytics** cuenta `generate_lead` al volver a `#contacto-enviado`, no al apretar Enviar:
  solo suman los que llegaron.

## Campos

`nombre`*, `email`*, `telefono`, `loteadora`, `plan` (fly, pro, master, enterprise, no-se),
`parcelas`, `vuelo` (necesita que lo volemos; se cotiza aparte), `mensaje` (hasta 2.000
caracteres, conserva sus párrafos) y la trampa `sitio`.

## Fuera de alcance

- Captcha: si el campo trampa y el tope por IP no alcanzan, Turnstile (igual que las reservas).
- Purga de datos personales: pendiente para todo lo que guarda la consola.
