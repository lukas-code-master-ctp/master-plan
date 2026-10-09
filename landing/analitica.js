// Google Analytics 4 de tumasterplan.cl. Va en un archivo y no dentro de la página
// porque la CSP no deja correr scripts en línea: así basta con 'self'.
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }
gtag('js', new Date());
gtag('config', 'G-0BBZ42FZH8');

// Un contacto es generate_lead, el evento que GA4 sugiere para eso. El formulario se
// cuenta cuando la consola devuelve a #contacto-enviado, no al apretar Enviar: así
// solo suman los que de verdad llegaron.
if (location.hash === '#contacto-enviado') {
  gtag('event', 'generate_lead', { metodo: 'formulario' });
}

// El correo que se ofrece como alternativa abre el programa de correo: Analytics no
// lo ve como salida al no ser una página, así que se cuenta aparte.
document.addEventListener('click', (evento) => {
  const enlace = evento.target.closest('a[href^="mailto:"]');
  if (!enlace) return;
  gtag('event', 'generate_lead', { metodo: 'correo', boton: enlace.textContent.trim() });
});
