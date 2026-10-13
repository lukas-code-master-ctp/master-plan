/** El detalle de un loteo: cómo se nombran las vistas y qué dice el medidor del sol. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  avisoAlQuitar, hayVistaPrevia, medicionDelSol, nombreDeVista, notaDePublicar, urlDeVistaPrevia,
} from './js/detalle.js';

test('cada vista se nombra como en el visor: punto en romanos y altura', () => {
  assert.equal(nombreDeVista('p01-500.jpg'), 'Punto I · 500 m');
  assert.equal(nombreDeVista('p04-500'), 'Punto IV · 500 m');
  assert.equal(nombreDeVista('p29-300.jpg'), 'Punto XXIX · 300 m');
});

test('una vista bajo el despegue dice cuánto más abajo', () => {
  assert.equal(nombreDeVista('p01--10.jpg'), 'Punto I · −10 m');
});

test('un nombre que no es de vista se muestra tal cual, sin la extensión', () => {
  assert.equal(nombreDeVista('vista-rara.jpg'), 'vista-rara');
});

test('el medidor toma el peor punto y lo compara con el límite de 3°', () => {
  const sol = medicionDelSol([{ error_sol: 0.19 }, { error_sol: 0.77 }, { error_sol: 0.05 }]);

  assert.equal(sol.peor, 0.77);
  assert.equal(sol.revisar, false);
  assert.ok(Math.abs(sol.fraccion - 0.77 / 3) < 1e-9);
});

test('sobre 3° pide revisar y el medidor queda lleno', () => {
  const sol = medicionDelSol([{ error_sol: 4.2 }]);

  assert.equal(sol.revisar, true);
  assert.equal(sol.fraccion, 1);
});

test('sin vistas no hay medición', () => {
  assert.equal(medicionDelSol([]), null);
});

test('quitar uno sin pagar avisa que borra el vuelo', () => {
  const aviso = avisoAlQuitar({ nombre: 'Loteo', subido: true, pagado: false, publicado: false });
  assert.match(aviso, /Se borran también el vuelo subido/);
  assert.match(aviso, /No se puede deshacer/);
  assert.doesNotMatch(aviso, /reservas/);
});

test('quitar uno pagado sin publicar no borra archivos', () => {
  assert.equal(avisoAlQuitar({ nombre: 'Loteo', subido: true, pagado: true, publicado: false }),
    '¿Quitar "Loteo" de la lista? No se borra ningún archivo.');
});

test('quitar uno publicado avisa que el sitio queda sin reservas', () => {
  const aviso = avisoAlQuitar({ nombre: 'Loteo', subido: true, pagado: true, publicado: true,
    url: 'https://loteo.vercel.app/' });
  assert.match(aviso, /https:\/\/loteo\.vercel\.app\/ sigue en línea, pero deja de recibir reservas/);
  assert.match(aviso, /solicitudes de reserva, las confirmadas incluidas/);
  assert.doesNotMatch(aviso, /No se borra ningún archivo/);
});

test('sin pago, la nota invita a pedir la habilitación', () => {
  const nota = notaDePublicar({ pagado: false, habilitacion_pedida: null, construido: true });

  assert.match(nota, /pide que lo habilitemos/);
  assert.doesNotMatch(nota, /escríbenos/);
});

test('ya pedida, la nota dice cuándo y que llega un correo', () => {
  const nota = notaDePublicar({
    pagado: false, habilitacion_pedida: '2026-10-13T15:00:00+00:00', construido: true,
  });

  assert.match(nota, /Pediste habilitarlo el 13 de octubre/);
  assert.match(nota, /te avisamos por correo/);
});

test('pagado, la nota vuelve a hablar de construir y publicar', () => {
  assert.match(notaDePublicar({ pagado: true, construido: false }), /una vez construido/);
  assert.equal(notaDePublicar({ pagado: true, construido: true, publicado: false, url: 'https://x' }),
    'Va a quedar en https://x');
});

test('la vista previa se ofrece construido y sin publicar, aunque no esté pagado', () => {
  const base = { slug: 'praderas', construido: true, publicado: false, pagado: false, trabajo: null };

  assert.equal(hayVistaPrevia(base), true);
  assert.equal(hayVistaPrevia({ ...base, construido: false }), false);
  // Publicado ya tiene "Ver sitio".
  assert.equal(hayVistaPrevia({ ...base, publicado: true }), false);
  // Construir rehace el sitio: a medio camino se vería roto.
  assert.equal(hayVistaPrevia({ ...base, trabajo: { accion: 'construir' } }), false);
  assert.equal(urlDeVistaPrevia(base), '/vista-previa/praderas/');
});
