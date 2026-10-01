"""Crea tu KMZ: del plano aprobado (PDF escaneado o foto) a los lotes de la subdivisión.

    python -m pipeline.plano digitalizar <carpeta-del-plano>

- `pagina`: la imagen de la página tal como viene en el PDF, rotada, recortada y,
  si es una foto, rectificada por las 4 esquinas del marco.
- `tinta`: qué píxeles son trazo de deslinde (tinta roja o negra).
- `particion`: regiones cerradas con las semillas de los rótulos, red de deslindes
  compartidos y polígonos por lote.
- `digitalizar`: el paso completo, de `entradas.json` a `digitalizado.json`.
"""
