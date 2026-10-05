# nuvalli-qr-etiquetas

Etiquetas de corte con QR hacia las hojas de perforación de PolyBoard.

Cruza el CSV de etiquetas de Opticut con el PDF exportado de PolyBoard por
**mueble + tipo de pieza** (sin medidas) y genera:

| Salida | Qué es |
|---|---|
| `hojas/<codigo>.png` | Una imagen por mueble + tipo de pieza (1 hoja, o varias apiladas si la etiqueta no distingue). Con `--formato pdf` salen como PDF |
| `reporte_match.csv` | Qué enlazó, a qué páginas de PB, y qué no |
| `etiquetas_qr.html` | Etiquetas con el mismo formato que la WebApp (Avery 5160, 3×10, Carta) más el QR |

## Instalación

```
pip install -r requirements.txt
```

## Uso

```
python qr_etiquetas.py PB.pdf etiquetas.csv                        # hojas + reporte
python qr_etiquetas.py PB.pdf etiquetas.csv --demo                 # QR de prueba
python qr_etiquetas.py PB.pdf etiquetas.csv --enlaces enlaces.csv  # enlaces de Drive (archivo;url)
python qr_etiquetas.py PB.pdf etiquetas.csv --base-url https://qr.nuvalli.com/h/
```

Opciones: `--salida CARPETA`, `--qr-mm 15`, `--formato png|pdf`, `--nombre "NOMBRE DE LA OPTIMIZACIÓN"`.

Imprimir el HTML desde Chrome a escala 100 % y márgenes "Ninguno", igual que
las etiquetas de la WebApp.

## Reglas del cruce

- Llave: mueble + tipo de pieza. Se ignoran mayúsculas, acentos, espacios y
  guiones; `(1)` y `[1]` son equivalentes.
- "Lateral Derecho, Lateral Izquierdo" abre las dos hojas.
- Si PB trunca el nombre (`...`), se cruza por prefijo.
- Si ninguna hoja de PB de la pieza trae operaciones, queda excluida: no
  genera hoja ni lleva QR. Se detecta por el contenido de la hoja (parámetros
  "Nombre: valor" de la operación o cotas "LETRA (x, y)" en el dibujo), no por
  listas de nombres. Cuando PB agregue operaciones a una pieza, entra sola.
- Sin coincidencia no hay QR: la etiqueta sale como hoy y queda en el reporte
  con una sugerencia. Nunca se adivina.

## Formato de etiquetas

`CSS_ETIQUETAS`, `parsear_etiquetas_opticut()` y `generar_html_etiquetas()`
son un port 1:1 de `_CSS_ETIQUETAS`, `parsearEtiquetasOpticut()` y
`generarHTMLEtiquetas()` de la WebApp (GAS). **Si cambia el formato allá, hay
que cambiarlo aquí.**

Lo único agregado es `CSS_QR`: en las etiquetas con QR el texto ocupa la
columna izquierda y el QR la derecha. En esas etiquetas, el texto que no cabe
se reduce de tamaño; mueble y tipo de pieza pueden partirse en dos renglones.

## Integración (pendiente)

`procesar(pdf_pb, csv_texto, nombre_opti, url_de, qr_mm)` es el punto de
entrada único para la API: recibe bytes/texto y devuelve hojas, reporte, HTML
y resumen, sin tocar disco.

## Por qué imágenes y no un PDF por mueble

El visor de Drive no abre un PDF en una página específica desde un enlace, así
que un PDF por mueble abriría siempre en la primera hoja. Cada pieza necesita
su propio archivo. En PNG pesa unas 7 veces menos que en PDF, porque cada PDF
partido repite las fuentes completas del original.
