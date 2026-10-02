# Mis KMZ: cajas que se desbordan y coordenadas en grados, minutos y segundos

## Problemas (QA del usuario, 2026-10-02)

Son dos temas independientes.

1. Al numerar un lote sobre el plano, la caja flotante "Número del lote que está aquí"
   no calza con su contenido: el campo de texto y el botón OK quedan fuera del recuadro.
2. En el "ir a coordenadas" del paso Ubicar, Google Earth entrega coordenadas como `34°10'37.50"S 71°32'53.89"W` y el "ir a" solo
   entiende decimales.

## Solución

1. CSS de la caja flotante del número: el recuadro debe envolver el campo y el botón
   (`box-sizing`, ancho del campo acotado, `min-width: 0` en el campo flexible, botón que
   no se encoge). Solo esa caja; el "ir a" no tiene este problema.
2. Un lector de coordenadas puro (`leerCoordenadas(texto)`) en `kmz_geometria.js` que
   acepte:
   - decimales `-34.98, -71.24`;
   - grados, minutos y segundos con hemisferio `34°10'37.50"S 71°32'53.89"W`;
   - variantes de símbolos (`º`, `′`, `″`, comillas tipográficas, espacios, coma o
     espacio entre ambas);
   - grados y minutos decimales `34°10.625'S`;
   - hemisferio adelante o atrás.

   Valida los rangos y devuelve null si no entiende, con un aviso claro. El "ir a" lo usa.

## Aceptación

- `node --test` cubre los formatos anteriores, incluido el ejemplo del usuario →
  -34.177083, -71.548303.
- La caja del número calza con su recuadro en el navegador, también cerca de los bordes del
  plano y con un zoom distinto.
