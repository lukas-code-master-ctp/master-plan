// Google Analytics 4 de tumasterplan.cl. Va en un archivo y no dentro de la página
// porque la CSP no deja correr scripts en línea: así basta con 'self'.
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }
gtag('js', new Date());
gtag('config', 'G-0BBZ42FZH8');

// Los botones de cotizar y pedir cuenta abren el correo: Analytics no los ve como
// salidas al no ser una página, así que se cuentan aparte. generate_lead es el
// evento que GA4 sugiere para un contacto comercial.
document.addEventListener('click', (evento) => {
  const enlace = evento.target.closest('a[href^="mailto:"]');
  if (!enlace) return;
  gtag('event', 'generate_lead', { metodo: 'correo', boton: enlace.textContent.trim() });
});
