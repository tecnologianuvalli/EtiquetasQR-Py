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
python qr_etiquetas.py CL03.pdf CL04.pdf CL05.pdf etiquetas.csv    # un nivel: varios PDF
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

### Coincidencia aproximada (nombres editados al exportar)

**Pieza.** Si el nombre no coincide exacto (se acortó, perdió acentos, se
abrevió o tiene una errata), se compara por palabras: las del nombre más corto
deben aparecer, en orden, en el más largo (`Frente Cajon EXTENSION` ~
`Frente Cajón EXTENSIÓN Vista Lluvia (inferior)`), o ambos deben empezar igual
en al menos dos palabras y la mitad del nombre (`Fondo Cajon EXTENSIÓN 50CM` ~
`Fondo Cajon EXTENSIÓN Vista Lluvi...`).

**Mueble.** Al exportar se editan las medidas de su nombre (`ALMIC-2P-75-10` en
Opticut es `ALMIC-2P-91-70-30-F15MM` en PB) y también la numeración de
instancias (`[1]`, `[2]` en Opticut; sin número y `[1]` en PB). Lo que no cambia
es el **código** (lo anterior a la primera medida: `ALMIC-2P`, `GACAJ-3C-EXT`).
Si el mueble no existe con su nombre en PB, sus candidatos son los muebles de PB
con el mismo código (o un nombre parecido), y lo eligen **todas sus piezas**:
gana el candidato donde encajan más de ellas (nombre + medidas + espesor), y
debe explicar al menos la mitad. Así el techo o la puerta, que delatan el ancho
real, deciden también por los laterales, que miden igual en varios muebles.
Si dos candidatos empatan:

- si son **gemelos** (misma perforación hoja por hoja, aunque PB los numere
  distinto) se reparten en orden: da igual cuál se enlace;
- si no (p. ej. mismas medidas pero una puerta con bisagra y otra sin), queda
  **sin QR** con la nota "Ambigua": no se adivina por la numeración.

Para que nunca abra una hoja equivocada, toda coincidencia aproximada exige:

- **las medidas y el espesor de la etiqueta son los de la hoja de PB**
  (tolerancia 0.6 mm, en cualquier orientación: Opticut a veces redondea el
  medio milímetro, 284 por 284.5), y
- **queda una sola pieza de PB posible**. Si varias se parecen al nombre y
  miden igual, desempata el tablero; si tampoco, queda **sin QR** con la nota
  "Ambigua" (p. ej. `Fondo Cajon IMPAZ` con CHICO y GRANDE de 497.5 × 299).

Un nombre acortado que agrupa piezas distintas (`Frente Cajon EXTENSION` para
inferior, intermedio y superior) se reparte por medidas: cada etiqueta enlaza
su propia hoja. En los códigos, números y letras son exactos (`3C` no es `2C`,
`ALMIC-2P` no es `ALMIC-3P`).

### Varios PDF de PolyBoard (un corte por nivel)

A producción se manda un corte por nivel y por prototipo: todas las cocinas,
todos los closets… Un departamento suele tener dos o tres closets distintos y
cada uno es un proyecto de PB con su PDF, así que un mismo CSV se cruza con
varios PDF a la vez (`pdf_pb`, `pdf_pb_2`, `pdf_pb_3`…; hasta 12).

- Cada mueble de PB se identifica por **PDF + nombre**: dos closets pueden tener
  un mueble que se llama igual con piezas distintas (`VISTA-10-120-1.5`,
  `CLMTRO2-03-200-60`…). Si el nombre del CSV existe en un solo PDF, se cruza
  como siempre; si existe en varios, lo eligen las piezas (medidas y espesor),
  igual que con un nombre aproximado.
- Se decide por mueble **y proyecto del CSV**: en un nivel, el "VISTA INF" del
  closet 03 y el del 04 son piezas distintas.
- Si aun así empatan, desempata el proyecto: cuando solo uno de los PDF se
  llama como el de las etiquetas (`CLOSET-03 D203` ~ el encabezado `Closet 03`
  de PB). Si son gemelos (misma perforación hoja por hoja), da igual cuál. Si
  no, "Ambigua".
- El reporte dice de qué PDF es cada hoja (`Closet 03: 12 13`) y
  `resumen.pdfs` cuántas etiquetas cubrió cada uno. **Un PDF con 0 etiquetas casi
  seguro es de otro proyecto o de otra versión del diseño** (otro fondo, otras
  correderas): la WebApp lo avisa.
- Un PDF subido dos veces se ignora. Con un solo PDF todo queda igual que antes
  (mismas hojas y mismos nombres de archivo).

### Piezas libres de PolyBoard

PB llama a las piezas libres con un nombre genérico (`PIEZA LIBRE COLOR`); en
Opticut llevan su nombre real (`Costado`, `Vista Inferior`). Por eso se
reconocen por **medidas y espesor** dentro de su mueble, aunque el nombre no se
parezca, y solo si ninguna otra pieza del mueble se llama parecido. Si dos piezas
libres miden igual y perforan distinto, queda "Ambigua". Si en Opticut un mueble
agrupa piezas libres que en PB son muebles separados (`COSTADO REFRI` → dos
`COSTADO-…`), cada etiqueta va a su propio mueble cuando sus medidas lo señalan en
uno solo. Una pieza libre sin perforación sale **EXCLUIDA**, no como error.

El código del mueble también se acepta cuando uno es el inicio del otro, palabra
por palabra (`VISTA INF` ~ `VISTA-10-120-1.5`), siempre confirmado por las piezas.

### Qué dice cada nota

"Medir" siempre es la **medida real de la pieza**: largo × ancho × espesor de la
etiqueta contra Altura × Anchura × Espesor de la hoja de PB (los números del
nombre del mueble nunca se usan para medir). "Encajar" es nombre parecido +
mismas medidas.

- `«Lateral Derecho» mide 2049 × 579 y en PB «Lateral Derecho» mide 2049 × 599`:
  la pieza existe, pero mide distinto (otra versión del diseño).
- `«Costado» mide igual que «Lateral» de PB, pero el nombre no se parece`.
- `«Suelo» mide 599 × 2000 y la pieza libre de PB más parecida mide 599 × 2030`.
- `El mueble se parece a «X» de PB, pero solo 9 de sus 37 piezas encajan ahí`:
  para elegir un mueble por aproximación tiene que encajar al menos la mitad de
  sus piezas; si no, ninguna lleva QR (y la nota da ejemplos de las que no encajan).
- `Mueble no existe en PB`: ni el nombre ni el código del mueble aparecen en ningún PDF.

La coincidencia exacta de siempre va primero y no cambia: mismos grupos y
mismos nombres de archivo, así que los QR ya impresos siguen sirviendo. Las
aproximadas salen en el reporte como `OK (aproximado)` con la pieza de PB con
la que enlazaron, para revisarlas; `resumen.aproximadas` las cuenta.

Pruebas: `python test_cruce.py`.

## Formato de etiquetas

`CSS_ETIQUETAS`, `parsear_etiquetas_opticut()` y `generar_html_etiquetas()`
son un port 1:1 de `_CSS_ETIQUETAS`, `parsearEtiquetasOpticut()` y
`generarHTMLEtiquetas()` de la WebApp (GAS). **Si cambia el formato allá, hay
que cambiarlo aquí.**

Lo único agregado es `CSS_QR`: en las etiquetas con QR el texto ocupa la
columna izquierda y el QR la derecha. En esas etiquetas, el texto que no cabe
se reduce de tamaño; mueble y tipo de pieza pueden partirse en dos renglones.

**Piezas libres:** en la etiqueta (con o sin QR) se imprime solo su
descripción: `PIEZA LIBRE COLOR MTRO 2BLE MEDIDA (345X670)` →
`MTRO 2BLE MEDIDA (345X670)`; también con solo `PIEZA LIBRE`. Si no trae nada
más se imprime tal cual. Solo cambia lo impreso: el cruce con PB usa el nombre
completo. `tipo_pieza_etiqueta()` es espejo de `tipoPiezaEtiqueta()` de la
WebApp; si cambia una, hay que cambiar la otra.

## API (Render Web Service)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Variable de entorno: `API_KEY` (también se acepta `APY_KEY`). La clave no va
  en el código ni en el repositorio.

Todas las llamadas, menos `/salud`, llevan el header `X-API-Key`.

| Endpoint | Entrada (multipart) | Salida (JSON) |
|---|---|---|
| `GET /salud` | — | `{"ok": true}` |
| `POST /procesar` | `pdf_pb` (y `pdf_pb_2`, `pdf_pb_3`… con varios), `csv_etiquetas`, `nombre`, `formato` (opcional) | `resumen`, `reporte`, `hojas: [{archivo, mime, base64}]` |
| `POST /etiquetas` | `pdf_pb` (y `pdf_pb_2`…), `csv_etiquetas`, `nombre`, `enlaces` (JSON `{archivo: url}`), `qr_mm` (opcional) | `resumen`, `html` |

El servicio no guarda nada entre llamadas. Flujo: `/procesar` → quien llama
sube las hojas y obtiene sus enlaces → `/etiquetas` con esos enlaces.

Errores: 401 clave inválida, 400 parámetros mal formados, 413 archivo mayor a
30 MB, 422 el PDF o el CSV no son lo esperado.

## Por qué imágenes y no un PDF por mueble

El visor de Drive no abre un PDF en una página específica desde un enlace, así
que un PDF por mueble abriría siempre en la primera hoja. Cada pieza necesita
su propio archivo. En PNG pesa unas 7 veces menos que en PDF, porque cada PDF
partido repite las fuentes completas del original.
