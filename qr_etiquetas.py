#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qr_etiquetas.py — Nuvalli: etiquetas de corte con QR hacia las hojas de
perforación de PolyBoard.

Cruza el CSV de etiquetas de Opticut con el PDF exportado de PolyBoard por
MUEBLE + TIPO DE PIEZA (sin usar medidas) y genera:

  hojas/<codigo>.png    Una imagen por mueble + tipo de pieza (o .pdf con --formato pdf)
  reporte_match.csv     Qué enlazó, a qué páginas de PB, y qué no
  etiquetas_qr.html     Las etiquetas, con el MISMO formato que la WebApp
                        (Avery 5160, 3 x 10, Carta) más el QR

El HTML se imprime igual que el de la WebApp: Chrome, escala 100 %, márgenes
"Ninguno".

USO
  python qr_etiquetas.py PB.pdf etiquetas.csv                   (hojas + reporte)
  python qr_etiquetas.py CL03.pdf CL04.pdf CL05.pdf etiquetas.csv   (un nivel: varios PDF)
  python qr_etiquetas.py PB.pdf etiquetas.csv --enlaces enlaces.csv
  python qr_etiquetas.py PB.pdf etiquetas.csv --base-url https://qr.nuvalli.com/h/
  python qr_etiquetas.py PB.pdf etiquetas.csv --demo            (QR de prueba)

  Opciones: --salida CARPETA   --qr-mm 15   --formato png|pdf   --nombre "NOMBRE DE LA OPTIMIZACIÓN"

Las funciones parsear_etiquetas_opticut() y generar_html_etiquetas() son un
port 1:1 de parsearEtiquetasOpticut() y generarHTMLEtiquetas() de la WebApp
(GAS). Si se cambia el formato allá, hay que cambiarlo aquí también.
"""
import argparse
import csv
import difflib
import hashlib
import html
import io
import os
import re
import sys
import unicodedata
from collections import OrderedDict, defaultdict

import pypdfium2 as pdfium
import segno
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth

POR_HOJA = 30

# ============================================================================
# CSS — copia literal de _CSS_ETIQUETAS de la WebApp (NO editar aquí sin
# editar allá). La geometría Avery 5160 vive en .hoja y .grid.
# ============================================================================
CSS_ETIQUETAS = (
    '@page{size:letter;margin:0}'
    '*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}'
    'html,body{margin:0;padding:0}'
    'body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff}'
    '.barra{position:sticky;top:0;z-index:10;background:#111;color:#fff;padding:10px 14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px}'
    '.barra .btn{background:#fff;color:#111;border:0;border-radius:6px;padding:7px 12px;font-weight:bold;font-size:13px;cursor:pointer}'
    '.barra .btn:hover{background:#e5e7eb}'
    '.barra .hint{color:#cbd5e1;font-size:12px}'
    '#modo-recuadro{position:absolute;left:-9999px}'
    '.hoja{box-sizing:border-box;width:8.5in;height:11in;padding:.5in .1875in;margin:0 auto;page-break-after:always;overflow:hidden}'
    '.hoja:last-child{page-break-after:auto}'
    '.grid{display:grid;grid-template-columns:repeat(3,2.625in);grid-auto-rows:1in;column-gap:.125in;row-gap:0}'
    '.et{box-sizing:border-box;overflow:hidden;padding:1.2mm 2mm;display:flex;flex-direction:column;justify-content:center;text-align:center;line-height:1.12}'
    '.et .l{font-size:7pt;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
    '.et .archivo{font-size:6pt;color:#333}'
    '.et .medidas{font-size:7.5pt}'
    '.et-panel .resalte{font-weight:800;font-size:9.5pt}'
    '#modo-recuadro:checked ~ .contenido .et-panel .resalte{align-self:center;display:inline-block;background:#000;color:#fff;font-weight:800;font-size:8.5pt;border-radius:2px;padding:0 2mm;margin:1px 0}'
    '.et-panel{background-origin:border-box;background-repeat:no-repeat;'
    'background-image:linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000),linear-gradient(#000,#000);'
    'background-size:4mm .4mm,.4mm 4mm,4mm .4mm,.4mm 4mm,4mm .4mm,.4mm 4mm,4mm .4mm,.4mm 4mm;'
    'background-position:left 1.5mm top 1.5mm,left 1.5mm top 1.5mm,right 1.5mm top 1.5mm,right 1.5mm top 1.5mm,left 1.5mm bottom 1.5mm,left 1.5mm bottom 1.5mm,right 1.5mm bottom 1.5mm,right 1.5mm bottom 1.5mm}'
    '.et-pieza .fuerte{font-weight:700;font-size:8pt}'
    '.et-pieza .mat{font-size:6.5pt}'
    '.et-pieza .mueble{font-weight:700;font-size:8.5pt}'
    '.et-pieza .inv{align-self:center;display:inline-block;max-width:100%;background:#000;color:#fff;font-weight:800;font-size:8.5pt;border-radius:2px;padding:0 2mm;margin:1px 0}'
    '#modo-recuadro:checked ~ .contenido .et-pieza .inv{display:block;max-width:none;background:none;color:#000;font-weight:800;font-size:9.5pt;border-radius:0;padding:0;margin:0}'
    '@media screen{body{background:#e5e7eb}.hoja{background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.25);margin:14px auto}}'
    '@media print{.barra{display:none!important}}'
)

# Único agregado al CSS: la etiqueta de pieza CON QR pasa a dos columnas
# (texto | QR). La etiqueta sin QR queda idéntica a la de la WebApp.
CSS_QR = (
    '.et-qr{flex-direction:row;align-items:center;gap:%(gap)smm}'
    '.et-qr .txt{flex:1 1 0;min-width:0;display:flex;flex-direction:column;justify-content:center;text-align:center}'
    '.et-qr .qr{flex:0 0 %(qr)smm;width:%(qr)smm;height:%(qr)smm}'
    '.et-qr .qr svg{display:block;width:100%%;height:100%%}'
)
QR_GAP_MM = 1.5
MM_A_PT = 72 / 25.4
# Formato de las hojas que se suben: 'png' (una imagen por pieza, ~30 KB por
# página) o 'pdf' (~215 KB por página, porque cada archivo repite las fuentes).
FORMATO_HOJAS = 'png'
PNG_DPI = 150

PT_UNA_LINEA = 6.5   # hasta aquí se encoge el texto antes de partirlo en dos renglones
PT_MIN = 5           # tamaño mínimo absoluto en etiquetas con QR


# ============================================================================
# 1) CSV de Opticut  — port de parsearEtiquetasOpticut()
# ============================================================================
def _mnum(v):
    """Normaliza numéricos escritos distinto ("2049.00", "2049", "2049,00")."""
    s = (v or '').strip()
    if re.fullmatch(r'-?\d+([.,]\d+)?', s):
        n = float(s.replace(',', '.'))
        return str(int(n)) if n == int(n) else repr(n)
    return s


def _firma_fila(cols):
    partes = [_mnum(c) for c in cols]
    while partes and partes[-1] == '':
        partes.pop()
    return '|'.join(partes)


def decodificar(datos):
    try:
        return datos.decode('utf-8-sig')
    except UnicodeDecodeError:
        return datos.decode('latin-1')


def parsear_etiquetas_opticut(raw_text):
    lineas = re.split(r'\r?\n', raw_text or '')
    primera = next((l for l in lineas if l.strip()), '')
    delim = ';' if len(primera.split(';')) >= len(primera.split(',')) else ','

    def col(cols, i):
        return cols[i].strip() if i < len(cols) else ''

    esquemas, huerfanas, actual = [], [], None
    n_piezas = n_retales = 0
    for linea in lineas:
        if not linea.strip():
            continue
        cols = linea.split(delim)
        tipo = col(cols, 0)
        if tipo == 'Pa':
            actual = dict(panel=dict(largo=col(cols, 1), ancho=col(cols, 2), material=col(cols, 3),
                                     espesor=col(cols, 4), referencia=col(cols, 5)),
                          piezas=[], firma=[_firma_fila(cols)])
            esquemas.append(actual)
        elif tipo == 'Pi':
            n_piezas += 1
            largo, ancho = col(cols, 1), col(cols, 2)
            c_izq_ancho, c_der_ancho = col(cols, 6), col(cols, 7)
            c_izq_largo, c_der_largo = col(cols, 8), col(cols, 9)
            pieza = dict(
                tipo='pieza', proyecto=col(cols, 11), material=col(cols, 3),
                mueble=col(cols, 10), tipo_pieza=col(cols, 5), largo=largo, ancho=ancho,
                medidas=('[' if c_izq_largo else '') + largo + (']' if c_der_largo else '') +
                        ' × ' +
                        ('[' if c_izq_ancho else '') + ancho + (']' if c_der_ancho else ''),
                espesor=col(cols, 4),
                cantos=[c_izq_ancho, c_der_ancho, c_izq_largo, c_der_largo],
                panelSKU=actual['panel']['material'] if actual else '')
            if actual:
                actual['piezas'].append(pieza)
                actual['firma'].append(_firma_fila(cols))
            else:
                huerfanas.append(pieza)
        elif tipo == 'Oc':
            n_retales += 1      # retal: no lleva etiqueta ni entra en la firma

    # Numeración por firma: esquemas idénticos comparten número ("N° 4 — 2/3")
    firma_a_num, total_por_num = {}, defaultdict(int)
    for e in esquemas:
        firma = '\n'.join(e['firma'])
        e['numero'] = firma_a_num.setdefault(firma, len(firma_a_num) + 1)
        total_por_num[e['numero']] += 1
    visto = defaultdict(int)
    for e in esquemas:
        visto[e['numero']] += 1
        e['repeticion'], e['totalReps'] = visto[e['numero']], total_por_num[e['numero']]

    items = list(huerfanas)
    for e in esquemas:
        items.append(dict(tipo='panel', esquema=e['numero'], repeticion=e['repeticion'],
                          totalReps=e['totalReps'], **e['panel']))
        for p in e['piezas']:
            p['esquema'], p['repeticion'] = e['numero'], e['repeticion']
            items.append(p)
    return dict(items=items, paneles=len(esquemas), esquemasUnicos=len(firma_a_num),
                piezas=n_piezas, retales=n_retales)


# ============================================================================
# 2) PDF de PolyBoard
# ============================================================================
RE_PIEZA = re.compile(
    r'^(?P<ref>.+?)\s+(?P<mat>\S+)\s+Altura:\s*(?P<alto>[\d.]+)\s+Anchura:\s*(?P<ancho>[\d.]+)\s+'
    r'Espesor:\s*(?P<esp>[\d.]+)\s+Cantidad:\s*\d+')
RE_PAGINA = re.compile(r'^P[áa]gina\s+\d+/\d+')

# ¿La hoja lleva trabajo? Se decide por lo que PB dibuja en ella, sin lista de
# nombres de operación ni de tipos de pieza:
#   - PB describe cada operación con parámetros "Nombre: valor"
#     (p. ej. "Diametro: 5  Profundidad: 8"), sea taladro, ranura u otra.
#   - y la acota en el dibujo como "LETRA (x, y)".
# Una hoja sin operaciones solo trae el contorno, los cantos y las medidas.
RE_PARAMETRO = re.compile(r'[^\W\d_]\w*:\s*\S')
RE_COTA_OPERACION = re.compile(r'\b[A-Z]{1,3}\s*\(\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\)')


def lleva_trabajo(lineas_de_la_hoja):
    """lineas_de_la_hoja: el texto de la hoja DESPUÉS del renglón de la pieza."""
    return any(RE_PARAMETRO.search(l) or RE_COTA_OPERACION.search(l) for l in lineas_de_la_hoja)


def norm(texto):
    """Mayúsculas, sin acentos, sin espacios/guiones; '(1)' y '[1]' equivalen."""
    t = unicodedata.normalize('NFKD', texto or '')
    t = ''.join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r'[\(\[]\s*(\d+)\s*[\)\]]\s*$', r'#\1', t.strip())
    return re.sub(r'[\s\-_.,]+', '', t)


def _truncado(t):
    return t.rstrip().endswith(('...', '…'))


def _sin_puntos(t):
    return re.sub(r'(\.\.\.|…)\s*$', '', t.rstrip())


# ----------------------------------------------------------------------------
# Coincidencia aproximada: nombres editados al exportar
# ----------------------------------------------------------------------------
# Opticut y PolyBoard no siempre traen el mismo texto: al exportar se acorta el
# nombre ("Frente Cajon EXTENSION" por "Frente Cajón EXTENSIÓN Vista Lluvia
# (inferior)"), se quitan acentos o palabras, se abrevia o PB trunca con "...".
# Si no hay coincidencia exacta se compara por palabras: las del nombre más
# corto deben aparecer, en orden, en el más largo (cada palabra puede venir
# abreviada o con una errata leve). Vale igual para el mueble y para la pieza.
#
# Para no mandar al perforador a una hoja equivocada, una coincidencia
# aproximada solo se acepta si:
#   - las MEDIDAS de la etiqueta son las de la hoja de PB (coinciden al décimo
#     de mm entre ambos programas), y
#   - queda UNA sola pieza de PB posible. Si varias se parecen al nombre y miden
#     igual (y ni el tablero las distingue), no se adivina: queda sin QR con la
#     nota "Ambigua". Así, un nombre acortado que agrupa piezas distintas
#     ("Frente Cajon EXTENSION" para inferior, intermedio y superior) se reparte
#     por medidas: cada etiqueta enlaza su propia hoja.
TOL_MM = 0.6


def _palabras(texto):
    """'Frente Cajón EXTENSIÓN (inferior)' -> ['FRENTE', 'CAJON', 'EXTENSION', 'INFERIOR'].
    El número de instancia del mueble ('[2]', '(2)' al final) queda como '#2'."""
    t = unicodedata.normalize('NFKD', texto or '')
    t = ''.join(c for c in t if not unicodedata.combining(c)).upper().strip()
    # PB trunca con "...": si cortó a media palabra ("Vista Ll..."), esa palabra no cuenta.
    a_media_palabra = bool(re.search(r'\w(\.\.\.|…)\s*$', t))
    t = re.sub(r'(\.\.\.|…)\s*$', '', t)
    t = re.sub(r'[\(\[]\s*(\d+)\s*[\)\]]\s*$', r' #\1', t)
    palabras = re.findall(r'#\d+|[A-Z0-9]+', t)
    if a_media_palabra and palabras:
        palabras.pop()
    return palabras


def _palabra_coincide(a, b):
    if a == b:
        return True
    if a[0] == '#' or b[0] == '#':
        return False                      # instancia del mueble: [2] no es [3]
    corta, larga = (a, b) if len(a) <= len(b) else (b, a)
    if corta.isdigit():
        return larga.startswith(corta) and larga[len(corta):].isalpha()     # 15 ~ 15MM; 1 no es 15
    if any(c.isdigit() for c in a + b):
        return False                      # códigos con números (F15MM, 3C): exactos
    if len(corta) >= 3 and larga.startswith(corta):
        return True                       # abreviatura: EXT ~ EXTENSION
    return len(corta) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85   # errata: EXTENCION


def _en_orden(cortas, largas):
    i = 0
    for p in largas:
        if i < len(cortas) and _palabra_coincide(cortas[i], p):
            i += 1
    return i == len(cortas)


def parecido(a, b):
    """¿a y b son el mismo nombre con palabras de menos, abreviadas o con una
    errata? Ignora acentos, mayúsculas y signos."""
    pa, pb = _palabras(a), _palabras(b)
    return bool(pa and pb) and (_en_orden(pa, pb) or _en_orden(pb, pa))


def _mismo_arranque(a, b):
    """¿Empiezan igual? Al menos 2 palabras en común al inicio y la mitad del
    nombre más corto: "Fondo Cajon EXTENSIÓN 50CM" ~ "Fondo Cajon EXTENSIÓN
    Vista Lluvi...". Solo se usa dentro de un mueble y con medidas iguales."""
    pa, pb = _palabras(a), _palabras(b)
    n = 0
    while n < min(len(pa), len(pb)) and _palabra_coincide(pa[n], pb[n]):
        n += 1
    return n >= 2 and n * 2 >= min(len(pa), len(pb))


def _mismo_nombre(csv, pb):
    """Coincidencia exacta (la de siempre): igual salvo mayúsculas, acentos,
    espacios y signos, o PB truncó con '...' y el resto coincide."""
    n_csv, n_pb = norm(csv), norm(_sin_puntos(pb))
    if n_pb == n_csv or (_truncado(pb) and n_csv.startswith(n_pb)):
        return True
    return not _truncado(pb) and _palabras(csv) == _palabras(pb)


def _mide_igual(it, p):
    """¿La etiqueta (largo x ancho y espesor de Opticut) mide lo que la hoja de PB
    (en cualquier orientación)? None si no se puede saber. Opticut a veces
    redondea el medio milímetro (284 por 284.5): de ahí la tolerancia."""
    try:
        l, a = float(it['largo']), float(it['ancho'])
    except (KeyError, TypeError, ValueError):
        return None
    if p.get('alto') is None:
        return None
    try:
        if p.get('esp') is not None and abs(float(it['espesor']) - p['esp']) > TOL_MM:
            return False
    except (KeyError, TypeError, ValueError):
        pass
    return ((abs(l - p['alto']) <= TOL_MM and abs(a - p['ancho']) <= TOL_MM) or
            (abs(l - p['ancho']) <= TOL_MM and abs(a - p['alto']) <= TOL_MM))


def _mismo_tablero(it, p):
    """Tablero de la etiqueta (SKU del panel en Opticut) vs. el de la hoja de PB,
    que PB suele truncar ('PAN-SAB-KRO-...-2070X...')."""
    sku, mat = (it.get('panelSKU') or '').upper(), (p.get('mat') or '').upper()
    if not sku or not mat:
        return False
    return sku.startswith(_sin_puntos(mat)) if _truncado(mat) else sku == mat


def _medidas(it):
    return f"{_mnum(it.get('largo'))} × {_mnum(it.get('ancho'))}"


PAGINAS_POR_PDF = 10000   # con varios PDF, la hoja n del PDF k es la página global k*10000+n


def leer_pb(pdf, indice=0):
    """pdf: ruta o bytes. Devuelve [dict(pagina, local, pdf, proyecto, mueble, ref, maquinado,
    alto, ancho, esp, mat, huella)].
    alto/ancho/esp: medidas de la pieza en mm; mat: código del tablero (PB lo trunca con "...");
    huella: resumen del texto de las operaciones (sin encabezado): dos hojas con la misma
    huella llevan la misma perforación aunque sean de muebles distintos (gemelos).
    pdf/local/proyecto: de qué PDF viene la hoja (índice y nombre del proyecto de PB del
    encabezado, p. ej. "Closet 03") y su página dentro de él; `pagina` es única entre todos
    los PDF (con uno solo, pagina == local)."""
    piezas, mueble_actual, proyecto = [], None, ''
    doc = pdfium.PdfDocument(pdf)
    try:
        for num in range(1, len(doc) + 1):
            texto = doc[num - 1].get_textpage().get_text_bounded() or ''
            lineas = [l.strip() for l in re.split(r'[\r\n]+', texto) if l.strip()]
            ini = next((i + 1 for i, l in enumerate(lineas[:6]) if RE_PAGINA.match(l)), None)
            if ini is None or len(lineas) <= ini + 1:
                continue
            if not proyecto and ini >= 2:
                proyecto = lineas[ini - 2]      # encabezado: "... PolyBoard 7.10p fecha / <proyecto> / Página n/m"
            cuerpo = lineas[ini:]
            m = RE_PIEZA.match(cuerpo[1])
            if m:
                # El mueble en la hoja de pieza puede venir truncado ("...F1...");
                # se usa el nombre completo de la portada si es consistente.
                mueble = cuerpo[0]
                if mueble_actual and norm(mueble_actual).startswith(norm(_sin_puntos(mueble))):
                    mueble = mueble_actual
                maquinado = lleva_trabajo(cuerpo[2:])
                piezas.append(dict(pagina=indice * PAGINAS_POR_PDF + num, local=num, pdf=indice,
                                   mueble=mueble, ref=m.group('ref').strip(),
                                   maquinado=maquinado, alto=float(m.group('alto')),
                                   ancho=float(m.group('ancho')), esp=float(m.group('esp')),
                                   mat=m.group('mat'),
                                   huella=hashlib.sha1('\n'.join(cuerpo[2:]).encode()).hexdigest()[:12]))
            elif re.match(r'^Altura\s+[\d.]+\s*mm', cuerpo[1]):
                mueble_actual = cuerpo[0]       # portada de mueble
    finally:
        doc.close()
    for p in piezas:
        p['proyecto'] = proyecto
    return piezas


def leer_pbs(pdfs):
    """Varios PDF de PolyBoard como si fueran uno: un corte por nivel junta varios
    prototipos (p. ej. tres closets), y cada uno es un proyecto de PB con su PDF.
    pdfs: lista de bytes/rutas o de (nombre, bytes). Un PDF repetido se ignora.
    Devuelve (piezas, docs) con docs = [dict(nombre, proyecto, datos, hojas_pb)]."""
    piezas, docs, vistos = [], [], set()
    for i, x in enumerate(pdfs):
        nombre, datos = x if isinstance(x, tuple) else (f'PDF {i + 1}', x)
        crudo = datos if isinstance(datos, (bytes, bytearray)) else open(datos, 'rb').read()
        huella = hashlib.sha1(crudo).hexdigest()
        if huella in vistos:
            continue
        vistos.add(huella)
        ps = leer_pb(crudo, len(docs))
        docs.append(dict(nombre=nombre, proyecto=ps[0]['proyecto'] if ps else '', datos=crudo, hojas_pb=len(ps)))
        piezas.extend(ps)
    return piezas, docs


def _origen(p, varios):
    """Mueble de PB tal como se muestra: con el proyecto (PDF) si hay varios."""
    return p['mueble'] + (f" ({p.get('proyecto') or 'PDF %d' % (p.get('pdf', 0) + 1)})" if varios else '')


def _paginas_txt(paginas, por_pagina, varios):
    """'12 13' con un PDF; 'Closet 03: 12 13; Closet 04: 5' con varios."""
    if not varios:
        return ' '.join(str(por_pagina.get(n, {}).get('local', n)) for n in paginas)
    por_pdf = OrderedDict()
    for n in paginas:
        p = por_pagina.get(n, {})
        por_pdf.setdefault(p.get('proyecto') or 'PDF %d' % (p.get('pdf', 0) + 1), []).append(str(p.get('local', n)))
    return '; '.join(f'{k}: {" ".join(v)}' for k, v in por_pdf.items())


# ============================================================================
# 3) Cruce mueble + tipo de pieza
# ============================================================================
def _resolver_pieza(it, ref, candidatas, exigir_medidas):
    """Hojas de PB de la pieza `ref` dentro de un mueble (candidatas), para la
    etiqueta `it`. Devuelve dict(paginas, aproximada, nota). Cada parte de
    "Lateral Derecho, Lateral Izquierdo" se busca por separado; basta con que
    una encuentre hoja (como siempre)."""
    paginas, aproximada, notas = [], False, []
    for parte in [x.strip() for x in ref.split(',') if x.strip()]:
        elegidas = [p for p in candidatas if _mismo_nombre(parte, p['ref'])]
        if elegidas and exigir_medidas:
            # El mueble se encontró por aproximación: las medidas confirman.
            elegidas = [p for p in elegidas if _mide_igual(it, p) is not False]
            if not elegidas:
                notas.append(f'«{parte}» existe en ese mueble pero no mide {_medidas(it)}')
        elif not elegidas:
            parecidas = [p for p in candidatas if parecido(parte, p['ref']) or _mismo_arranque(parte, p['ref'])]
            if not parecidas:
                continue
            # Una coincidencia aproximada exige que las medidas también coincidan.
            elegidas = [p for p in parecidas if _mide_igual(it, p) is not False]
            if not elegidas:
                ej = parecidas[0]
                notas.append(f'Parecida a «{ej["ref"]}» de PB, pero la etiqueta mide {_medidas(it)} '
                             f'y la hoja {ej["alto"]:g} × {ej["ancho"]:g}')
                continue
            refs = OrderedDict((norm(_sin_puntos(p['ref'])), p['ref']) for p in elegidas)
            if len(refs) > 1:
                # Desempate por tablero; si tampoco distingue, no se adivina.
                por_tablero = [p for p in elegidas if _mismo_tablero(it, p)]
                if por_tablero and len({norm(_sin_puntos(p['ref'])) for p in por_tablero}) == 1:
                    elegidas = por_tablero
                else:
                    notas.append('Ambigua: ' + ' y '.join(f'«{r}»' for r in refs.values()) +
                                 f' de PB se parecen al nombre y miden {_medidas(it)}; corrige el nombre')
                    continue
            aproximada = True
        for p in elegidas:
            if p['pagina'] not in paginas:
                paginas.append(p['pagina'])
    if not paginas:
        return dict(paginas=[], aproximada=False, nota='; '.join(notas))
    return dict(paginas=sorted(paginas), aproximada=aproximada, nota='')


def _resolver_en_mueble_exacto(it, piezas_mueble):
    """El mueble de la etiqueta existe con su nombre en PB: la de siempre."""
    r = _resolver_pieza(it, it['tipo_pieza'], piezas_mueble, exigir_medidas=False)
    if not r['paginas'] and not r['nota']:
        nombres = sorted({p['ref'] for p in piezas_mueble})
        cerca = difflib.get_close_matches(it['tipo_pieza'], nombres, n=1, cutoff=0.7)
        r['nota'] = 'Tipo de pieza no existe en ese mueble' + (f' (¿será {cerca[0]}?)' if cerca else '')
    return r


def _elegir_mueble(etiquetas, candidatos, por_mueble, muebles_pb, proyecto_csv='', proyecto_pb=None):
    """Mueble de PB para un mueble del CSV cuando no hay uno solo con su nombre:
    no existe con ese nombre en PB, o existe en varios PDF (dos closets de un
    mismo nivel con un mueble que se llama igual).

    Se decide con TODAS sus etiquetas: gana el candidato donde encajan más de
    ellas (nombre de pieza + medidas + espesor). Así las piezas que delatan el
    tamaño real (techo, suelo, puertas) eligen el mueble también para las que
    no lo delatan (laterales iguales en varios muebles).

    Si empatan, decide (en este orden): el proyecto, cuando solo uno de los PDF
    empatados se llama como el de las etiquetas ("CLOSET-03 D203" ~ "Closet 03");
    o que sean gemelos (misma perforación hoja por hoja), que da igual cuál.

    Devuelve dict(clave, gemelos) o dict(nota) si no se puede decidir."""
    proyecto_pb = proyecto_pb or {}
    puntos = OrderedDict()
    for k in candidatos:
        puntos[k] = sum(1 for it in etiquetas
                        if _resolver_pieza(it, it['tipo_pieza'], por_mueble[k], exigir_medidas=True)['paginas'])
    mejor = max(puntos.values()) if puntos else 0
    nombres = lambda ks: ' y '.join(f'«{muebles_pb[k]}»' for k in ks)
    if mejor == 0:
        return dict(nota=f'El mueble se parece a {nombres(candidatos)} de PB, pero sus piezas no miden como ahí')
    # El mueble elegido debe explicar al menos la mitad de sus etiquetas: si solo
    # encajan una o dos piezas genéricas (un lateral), no es evidencia suficiente.
    if mejor * 2 < len(etiquetas):
        return dict(nota=f'El mueble se parece a {nombres(candidatos)} de PB, pero solo {mejor} de sus '
                         f'{len(etiquetas)} piezas miden como ahí')
    empatados = [k for k, v in puntos.items() if v == mejor]
    if len(empatados) > 1 and proyecto_csv:
        del_proyecto = [k for k in empatados if proyecto_pb.get(k) and parecido(proyecto_csv, proyecto_pb[k])]
        if len(del_proyecto) == 1:
            empatados = del_proyecto
    if len(empatados) == 1:
        return dict(clave=empatados[0], gemelos=[empatados[0]])
    huellas = {k: sorted((norm(_sin_puntos(p['ref'])), p['alto'], p['ancho'], p['huella']) for p in por_mueble[k])
               for k in empatados}
    if len({tuple(h) for h in huellas.values()}) == 1:
        return dict(clave=empatados[0], gemelos=sorted(empatados, key=lambda k: muebles_pb[k]))
    return dict(nota=f'Ambigua: sus piezas encajan igual en {nombres(empatados)} de PB; corrige el nombre del mueble')


def _codigo_mueble(nombre):
    """Parte del nombre del mueble que no es medida: 'ALMIC-2P-91-70-30-F15MM' ->
    ('ALMIC', '2P'); 'GACAJ-3C-EXT-72-70-60' -> ('GACAJ', '3C', 'EXT'). Las medidas
    (y lo que sigue) se editan al exportar; el código no."""
    codigo = []
    for p in _palabras(nombre):
        if p.isdigit() or p[0] == '#':
            break
        codigo.append(p)
    return tuple(codigo)


def cruzar(items, piezas_pb):
    """OrderedDict[clave] -> dict(mueble, tipo_pieza, paginas, etiquetas, nota,
    codigo, excluida, aproximada, pdfs). Marca cada etiqueta con it['_grupo'] = clave.

    La clave es (mueble, tipo_pieza) del CSV, como siempre. Solo cuando las
    medidas reparten un mismo nombre entre piezas distintas de PB (un nombre
    acortado que agrupa inferior/superior, o un mueble que se llama igual en
    dos closets del nivel) el grupo se separa y la clave lleva además la pieza
    de PB: (mueble, tipo_pieza, '<pieza PB y medidas>').

    piezas_pb puede venir de varios PDF (leer_pbs): cada mueble de PB se
    identifica por (PDF, nombre), porque dos prototipos pueden tener muebles
    con el mismo nombre y piezas distintas."""
    por_mueble = defaultdict(list)
    for p in piezas_pb:
        por_mueble[(p.get('pdf', 0), norm(p['mueble']))].append(p)
    varios = len({k[0] for k in por_mueble}) > 1
    muebles_pb, nombre_pb, proyecto_pb = {}, {}, {}
    por_nombre = defaultdict(list)            # nombre normalizado -> muebles de PB (uno por PDF)
    for p in piezas_pb:
        k = (p.get('pdf', 0), norm(p['mueble']))
        if k not in muebles_pb:
            muebles_pb[k], nombre_pb[k], proyecto_pb[k] = _origen(p, varios), p['mueble'], p.get('proyecto', '')
            por_nombre[k[1]].append(k)
    por_pagina = {p['pagina']: p for p in piezas_pb}
    piezas = [it for it in items if it['tipo'] == 'pieza']

    # 1) Muebles del CSV sin UN mueble de PB con su nombre (no existe, o existe en
    #    varios PDF): se elige por las piezas entre los del mismo nombre, o entre
    #    los parecidos / del mismo código (sin las medidas). Se decide por mueble
    #    Y proyecto del CSV: en un nivel, "VISTA INF" del closet 03 y del 04 son
    #    piezas distintas. Los gemelos se reparten en orden.
    asignado, sin_mueble, gemelos = {}, {}, defaultdict(list)
    etiquetas_de = OrderedDict()
    for it in piezas:
        if len(por_nombre.get(norm(it['mueble']), [])) != 1:
            etiquetas_de.setdefault((it['proyecto'], it['mueble']), []).append(it)
    for (proyecto, mueble), ets in etiquetas_de.items():
        candidatos = por_nombre.get(norm(mueble), [])
        if not candidatos:
            codigo = _codigo_mueble(mueble)
            candidatos = [k for k, nombre in nombre_pb.items()
                          if parecido(mueble, nombre) or (codigo and _codigo_mueble(nombre) == codigo)]
        if not candidatos:
            cerca = difflib.get_close_matches(norm(mueble), sorted({k[1] for k in nombre_pb}), n=1, cutoff=0.8)
            sugerido = next((nombre_pb[k] for k in nombre_pb if cerca and k[1] == cerca[0]), '')
            sin_mueble[(proyecto, mueble)] = 'Mueble no existe en PB' + (f' (¿será {sugerido}?)' if sugerido else '')
            continue
        r = _elegir_mueble(ets, candidatos, por_mueble, muebles_pb, proyecto, proyecto_pb)
        if 'nota' in r:
            sin_mueble[(proyecto, mueble)] = r['nota']
        else:
            gemelos[tuple(r['gemelos'])].append((proyecto, mueble))
    for grupo_gemelos, muebles_csv in gemelos.items():
        for i, clave_csv in enumerate(sorted(muebles_csv)):
            asignado[clave_csv] = grupo_gemelos[i % len(grupo_gemelos)]

    # 2) Cada etiqueta. Las del mismo proyecto, nombre, medidas y tablero resuelven igual.
    cache, por_grupo = {}, OrderedDict()
    for it in piezas:
        firma = (it['proyecto'], it['mueble'], it['tipo_pieza'], _mnum(it['largo']), _mnum(it['ancho']),
                 it.get('panelSKU', ''))
        if firma not in cache:
            exactos = por_nombre.get(norm(it['mueble']), [])
            clave_csv = (it['proyecto'], it['mueble'])
            if len(exactos) == 1:
                cache[firma] = _resolver_en_mueble_exacto(it, por_mueble[exactos[0]])
            elif clave_csv in asignado:
                k = asignado[clave_csv]
                r = _resolver_pieza(it, it['tipo_pieza'], por_mueble[k], exigir_medidas=True)
                if r['paginas']:
                    # Con el mismo nombre en varios PDF no es aproximada: el nombre es
                    # exacto y las piezas eligieron el PDF.
                    r['aproximada'] = r['aproximada'] or not exactos
                elif not r['nota']:
                    r['nota'] = (f'Su mueble es «{muebles_pb[k]}» en PB, '
                                 f'pero ahí no hay «{it["tipo_pieza"]}» que mida {_medidas(it)}')
                cache[firma] = r
            else:
                cache[firma] = dict(paginas=[], aproximada=False, nota=sin_mueble[clave_csv])
        por_grupo.setdefault((it['mueble'], it['tipo_pieza']), []).append((it, cache[firma]))

    # 3) Grupos. Lo normal es que todo el grupo resuelva igual: misma clave y
    #    mismo nombre de archivo que antes (los QR ya impresos siguen sirviendo).
    grupos = OrderedDict()
    for (mueble, ref), lista in por_grupo.items():
        por_resultado = OrderedDict()
        for it, r in lista:
            # Identidad estable de las hojas (no el número de página, que cambia al
            # reexportar PB); con varios PDF incluye el proyecto de PB.
            hojas = '+'.join(sorted(
                (f"{por_pagina[n].get('proyecto', '')}/" if varios else '') +
                f"{norm(por_pagina[n]['mueble'])}/{norm(_sin_puntos(por_pagina[n]['ref']))}/"
                f"{por_pagina[n]['alto']:g}x{por_pagina[n]['ancho']:g}" for n in r['paginas']))
            por_resultado.setdefault(hojas or 'SIN:' + r['nota'], []).append((it, r))
        separar = len(por_resultado) > 1
        for firma_hojas, sub in por_resultado.items():
            r = sub[0][1]
            clave = (mueble, ref, firma_hojas) if separar else (mueble, ref)
            base = f'{norm(mueble)}|{norm(ref)}' + (f'|{firma_hojas}' if separar else '')
            g = dict(mueble=mueble, tipo_pieza=ref, paginas=list(r['paginas']), etiquetas=len(sub),
                     nota=r['nota'], codigo=hashlib.sha1(base.encode()).hexdigest()[:8],
                     excluida=False, aproximada=r['aproximada'],
                     pdfs=sorted({por_pagina[n].get('pdf', 0) for n in r['paginas']}))
            if g['paginas'] and (g['aproximada'] or separar):
                pb = OrderedDict()
                for n in g['paginas']:
                    p = por_pagina[n]
                    pb.setdefault((_origen(p, varios), p['ref']), f"{p['alto']:g} × {p['ancho']:g}")
                g['nota'] = ('Aproximada a PB: ' if g['aproximada'] else 'Por medidas: ') + '; '.join(
                    (f'«{m}» / ' if varios or norm(m) != norm(mueble) else '') + f'«{rf}» ({med})'
                    for (m, rf), med in pb.items())
            # Ninguna de sus hojas lleva trabajo: sin hoja y sin QR. Si al menos una
            # lleva, se conservan todas (p. ej. par de puertas), para que el
            # perforador vea cuál sí y cuál no. El día que PB agregue operaciones a
            # una pieza hoy excluida, entra sola: no hay nada que actualizar aquí.
            if g['paginas'] and not any(por_pagina[n]['maquinado'] for n in g['paginas']):
                g['excluida'] = True
                g['nota'] = ('Excluida: su hoja de PB no trae operaciones (pág. ' +
                             _paginas_txt(g['paginas'], por_pagina, varios) + ')')
                g['paginas'] = []
            grupos[clave] = g
            for it, _ in sub:
                it['_grupo'] = clave
    return grupos


_PALETA_16_GRISES = sum(([v * 17] * 3 for v in range(16)), [])


def _png_de_paginas(paginas):
    """Una sola imagen PNG con las páginas apiladas, en 16 tonos de gris
    (paleta fija de 4 bits: liviana y rápida de generar). paginas: [(doc, n)]."""
    imgs = [doc[n - 1].render(scale=PNG_DPI / 72, grayscale=True).to_pil() for doc, n in paginas]
    lienzo = Image.new('L', (max(i.width for i in imgs), sum(i.height for i in imgs)), 255)
    y = 0
    for i in imgs:
        lienzo.paste(i, (0, y))
        y += i.height
    indices = Image.eval(lienzo, lambda v: min(15, (v + 8) // 17))
    png = Image.frombytes('P', lienzo.size, indices.tobytes())
    png.putpalette(_PALETA_16_GRISES)
    buf = io.BytesIO()
    png.save(buf, 'PNG', bits=4, compress_level=6)
    return buf.getvalue()


def generar_hojas(pdf, grupos, formato=None, piezas_pb=None):
    """Devuelve {'<codigo>.<ext>': bytes} con las hojas de cada grupo enlazado.
    pdf: ruta o bytes, o la lista de PDF de leer_pbs() (entonces piezas_pb dice
    de qué PDF y página sale cada hoja)."""
    formato = formato or FORMATO_HOJAS
    docs = pdf if isinstance(pdf, list) else [pdf]
    ubicacion = {p['pagina']: (p.get('pdf', 0), p.get('local', p['pagina'])) for p in (piezas_pb or [])}
    donde = lambda n: ubicacion.get(n, (0, n))
    salida = {}
    if formato == 'png':
        abiertos = [pdfium.PdfDocument(d) for d in docs]
        try:
            for g in grupos.values():
                if g['paginas']:
                    salida[g['codigo'] + '.png'] = _png_de_paginas(
                        [(abiertos[i], n) for i, n in map(donde, g['paginas'])])
        finally:
            for d in abiertos:
                d.close()
        return salida
    lectores = [PdfReader(io.BytesIO(d) if isinstance(d, (bytes, bytearray)) else d) for d in docs]
    for g in grupos.values():
        if not g['paginas']:
            continue
        w = PdfWriter()
        for i, n in map(donde, g['paginas']):
            w.add_page(lectores[i].pages[n - 1])
        w.add_metadata({'/Title': f"{g['mueble']} — {g['tipo_pieza']}"})
        buf = io.BytesIO()
        w.write(buf)
        salida[g['codigo'] + '.pdf'] = buf.getvalue()
    return salida


def reporte_filas(grupos, piezas_pb, ext='png'):
    por_pagina = {p['pagina']: p for p in piezas_pb}
    varios = len({p.get('pdf', 0) for p in piezas_pb}) > 1
    usadas = {n for g in grupos.values() for n in g['paginas']}
    filas = [['estado', 'mueble', 'tipo_pieza', 'etiquetas', 'hojas', 'paginas_PB', 'archivo', 'nota']]
    for g in grupos.values():
        n = len(g['paginas'])
        if n == 0:
            estado = 'EXCLUIDA' if g['excluida'] else 'SIN ENLACE'
        elif g['aproximada']:
            estado = 'OK (aproximado)'      # enlazó sin nombre exacto: conviene revisarla
        else:
            estado = 'OK' if n == 1 else 'OK (varias hojas)'
        filas.append([estado, g['mueble'], g['tipo_pieza'], g['etiquetas'], n,
                      _paginas_txt(g['paginas'], por_pagina, varios),
                      f"{g['codigo']}.{ext}" if n else '', g['nota']])
    # Hojas de PB con operaciones que ninguna etiqueta usa.
    for p in piezas_pb:
        if p['pagina'] not in usadas and p['maquinado']:
            filas.append(['PB SIN ETIQUETA', _origen(p, varios), p['ref'], 0, 1,
                          _paginas_txt([p['pagina']], por_pagina, varios) if varios else p['pagina'], '',
                          'Hoja de PB que ninguna etiqueta usa'])
    return filas


# ============================================================================
# 4) HTML de etiquetas — port de generarHTMLEtiquetas() + QR
# ============================================================================
def _esc(v):
    return html.escape(str(v if v is not None else ''), quote=True)


def tipo_pieza_etiqueta(tipo):
    """Texto del tipo de pieza TAL COMO SE IMPRIME en la etiqueta: a las piezas
    libres se les quita "PIEZA LIBRE COLOR" (o "PIEZA LIBRE") y queda solo su
    descripción: "PIEZA LIBRE COLOR MTRO 2BLE MEDIDA (345X670)" -> "MTRO 2BLE
    MEDIDA (345X670)". Si no trae nada más, se deja como está (no se imprime un
    recuadro vacío). Solo cambia lo impreso: el cruce con PB usa el nombre completo.
    Espejo de tipoPiezaEtiqueta() de la WebApp (OrdenProduccion.html)."""
    original = str(tipo if tipo is not None else '')
    if not re.search(r'\bPIEZA\s+LIBRE\b', original, flags=re.IGNORECASE):
        return original                                   # el resto, intacto
    limpio = re.sub(r'\bPIEZA\s+LIBRE(\s+COLOR)?\b', ' ', original, flags=re.IGNORECASE)
    limpio = re.sub(r'\s{2,}', ' ', limpio)
    limpio = re.sub(r'^[\s\-–—,:;]+|[\s\-–—,:;]+$', '', limpio)
    return limpio or original


def _svg_qr(url):
    return segno.make(url, error='m', micro=False).svg_inline(border=2, omitsize=True)


def _linea(clase, texto, pt, negrita, ancho_pt, dos_lineas=False):
    """Línea de una etiqueta CON QR. Si el texto no cabe en el ancho que deja
    el QR se reduce la letra; si aun así no cabe y dos_lineas=True, se parte en
    dos renglones (mueble y tipo de pieza: lo que el perforador debe leer
    completo). Lo demás se recorta con "…" como en la WebApp."""
    fuente = 'Helvetica-Bold' if negrita else 'Helvetica'     # mismas métricas que Arial
    ancho = lambda t: stringWidth(texto, fuente, t)
    tam, estilo = pt, ''
    piso = PT_UNA_LINEA if dos_lineas else PT_MIN
    while tam > piso and ancho(tam) > ancho_pt:
        tam -= 0.25
    if dos_lineas and ancho(tam) > ancho_pt:
        while tam > PT_MIN and ancho(tam) > ancho_pt * 1.75:
            tam -= 0.25
        estilo = f'font-size:{tam:g}pt;white-space:normal;line-height:1.05'
    elif tam < pt:
        estilo = f'font-size:{tam:g}pt'
    return f'<div class="l {clase}"' + (f' style="{estilo}"' if estilo else '') + f'>{_esc(texto)}</div>'


def generar_html_etiquetas(nombre_opti, items, enlaces=None, qr_mm=15):
    """enlaces: {clave del grupo: url}, con la clave que cruzar() dejó en
    it['_grupo'] (o (mueble, tipo_pieza) si no se cruzó). Sin enlace, la
    etiqueta sale exactamente como la de la WebApp."""
    enlaces = enlaces or {}
    nombre = _esc(nombre_opti or '')
    n_piezas = sum(1 for it in items if it['tipo'] != 'panel')
    n_paneles = len(items) - n_piezas
    n_unicos = len({it['esquema'] for it in items if it['tipo'] == 'panel'})
    n_hojas = max(1, -(-len(items) // POR_HOJA))
    n_qr = 0

    # Ancho útil del texto junto al QR: 2.625in - relleno 2mm x2 - QR - separación
    ancho_txt = (2.625 * 72 - (4 + qr_mm + QR_GAP_MM) * MM_A_PT) * 0.95
    ancho_inv = ancho_txt - 4 * MM_A_PT          # los recuadros llevan 2mm por lado

    def etiqueta(it):
        nonlocal n_qr
        if it['tipo'] == 'panel':
            titulo = 'Esquema de Corte N° ' + _esc(it['esquema']) + (
                f" — {_esc(it['repeticion'])}/{_esc(it['totalReps'])}" if it['totalReps'] > 1 else '')
            return ('<div class="et et-panel">'
                    f'<div class="l resalte">{titulo}</div>'
                    f'<div class="l">{_esc(it["material"])}</div>'
                    f'<div class="l">{_esc(it["largo"])} × {_esc(it["ancho"])}</div>'
                    f'<div class="l">{_esc(it["referencia"])}</div>'
                    f'<div class="l archivo">{nombre}</div>'
                    '</div>')
        url = enlaces.get(it.get('_grupo') or (it['mueble'], it['tipo_pieza']))
        if not url:
            return ('<div class="et et-pieza">'
                    f'<div class="l fuerte">{nombre}</div>'
                    f'<div class="l inv">{_esc(it["proyecto"])}</div>'
                    f'<div class="l mat">{_esc(it["material"])}</div>'
                    f'<div class="l mueble">{_esc(it["mueble"])}</div>'
                    f'<div class="l inv">{_esc(tipo_pieza_etiqueta(it["tipo_pieza"]))}</div>'
                    f'<div class="l medidas">{_esc(it["medidas"])}</div>'
                    '</div>')
        n_qr += 1
        return ('<div class="et et-pieza et-qr"><div class="txt">' +
                _linea('fuerte', nombre_opti or '', 8, True, ancho_txt) +
                _linea('inv', it['proyecto'], 8.5, True, ancho_inv) +
                _linea('mat', it['material'], 6.5, False, ancho_txt) +
                _linea('mueble', it['mueble'], 8.5, True, ancho_txt, dos_lineas=True) +
                _linea('inv', tipo_pieza_etiqueta(it['tipo_pieza']), 8.5, True, ancho_inv, dos_lineas=True) +
                _linea('medidas', it['medidas'], 7.5, False, ancho_txt) +
                f'</div><div class="qr">{_svg_qr(url)}</div></div>')

    hojas = ''
    for h in range(0, len(items), POR_HOJA):
        hojas += ('<div class="hoja"><div class="grid">' +
                  ''.join(etiqueta(it) for it in items[h:h + POR_HOJA]) + '</div></div>')
    if not items:
        hojas = ('<p style="padding:24px;font-family:Arial;font-size:14px">'
                 'El CSV no contiene etiquetas de pieza ni de esquema de corte. '
                 '¿Seguro que es el export de <b>Etiquetas</b> de Opticut?</p>')

    cuerpo = ('<div class="barra">'
              '<button class="btn" onclick="window.print()">Imprimir</button>'
              '<label class="btn" for="modo-recuadro">Alternar estilo de resalte</label>'
              f'<span class="hint">{n_piezas} etiqueta(s) de pieza ({n_qr} con QR) · {n_paneles} de esquema'
              + (f' ({n_unicos} únicos)' if n_unicos < n_paneles else '') +
              f' · {n_hojas} hoja(s) Carta · Avery 5160 (3×10)</span>'
              '<span class="hint">Al imprimir: escala 100% (sin “ajustar a página”) y márgenes “Ninguno”.</span>'
              '</div><input type="checkbox" id="modo-recuadro"><div class="contenido">'
              + hojas + '</div>')
    css = CSS_ETIQUETAS + CSS_QR % dict(gap=QR_GAP_MM, qr=f'{qr_mm:g}')
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<title>Etiquetas — {_esc(nombre_opti or "Lote")}</title>'
            f'<style>{css}</style></head><body>{cuerpo}</body></html>')


# ============================================================================
# 5) Punto de entrada único (lo que llamará la API)
# ============================================================================
def procesar(pdf_pb, csv_texto, nombre_opti, url_de=None, qr_mm=15, formato=None, con_hojas=True):
    """pdf_pb: ruta o bytes, o lista de ellos / de (nombre, bytes) para varios PDF.
    url_de: función archivo ('<codigo>.<ext>') -> url (o None para no generar
    etiquetas). Devuelve dict con grupos, hojas, reporte, html, resumen.
    resumen.pdfs dice cuántas etiquetas cubrió cada PDF: uno con 0 seguramente
    no corresponde a este corte."""
    # Uno o varios PDF de PB: un corte por nivel junta varios prototipos (closets).
    piezas_pb, docs = leer_pbs(pdf_pb if isinstance(pdf_pb, list) else [pdf_pb])
    parse = parsear_etiquetas_opticut(csv_texto)
    grupos = cruzar(parse['items'], piezas_pb)
    formato = formato or FORMATO_HOJAS
    # con_hojas=False ahorra el trabajo de partir el PDF cuando solo se
    # necesita el HTML (segunda llamada de la API).
    hojas = generar_hojas([d['datos'] for d in docs], grupos, formato, piezas_pb) if con_hojas else {}

    enlaces = {}
    if url_de:
        for clave, g in grupos.items():
            url = url_de(f"{g['codigo']}.{formato}") if g['paginas'] else None
            if url:
                enlaces[clave] = url
    total = sum(g['etiquetas'] for g in grupos.values())
    return dict(
        grupos=grupos, hojas=hojas, reporte=reporte_filas(grupos, piezas_pb, formato),
        html=generar_html_etiquetas(nombre_opti, parse['items'], enlaces, qr_mm) if url_de else None,
        resumen=dict(
            hojas_pb=len(piezas_pb), archivos=sum(1 for g in grupos.values() if g['paginas']),
            peso_kb=round(sum(map(len, hojas.values())) / 1024), etiquetas=total, paneles=parse['paneles'],
            enlazan=sum(g['etiquetas'] for g in grupos.values() if g['paginas']),
            varias_hojas=sum(g['etiquetas'] for g in grupos.values() if len(g['paginas']) > 1),
            aproximadas=sum(g['etiquetas'] for g in grupos.values() if g['paginas'] and g['aproximada']),
            con_qr=sum(g['etiquetas'] for c, g in grupos.items() if c in enlaces),
            excluidas=sum(g['etiquetas'] for g in grupos.values() if g['excluida']),
            sin_enlace=[dict(mueble=g['mueble'], tipo_pieza=g['tipo_pieza'], nota=g['nota'])
                        for g in grupos.values() if not g['paginas'] and not g['excluida']],
            pdfs=[dict(nombre=d['nombre'], proyecto=d['proyecto'], hojas_pb=d['hojas_pb'],
                       etiquetas=sum(g['etiquetas'] for g in grupos.values() if i in g['pdfs']))
                  for i, d in enumerate(docs)]))


# ============================================================================
# CLI
# ============================================================================
def _resolver_urls(args):
    """Devuelve función archivo ('<codigo>.<ext>') -> url, o None."""
    if args.enlaces:
        texto = decodificar(open(args.enlaces, 'rb').read())
        delim = ';' if texto.count(';') >= texto.count(',') else ','
        mapa = {f[0].strip(): f[1].strip()
                for f in csv.reader(texto.splitlines(), delimiter=delim)
                if len(f) >= 2 and f[1].strip().lower().startswith('http')}
        return mapa.get
    if args.base_url:
        base = args.base_url.rstrip('/') + '/'
        return lambda archivo: base + archivo
    if args.demo:    # mismo largo que un enlace real de Drive
        return lambda archivo: f"https://drive.google.com/file/d/DEMO-{archivo[:8]}-{'x' * 19}/view"
    return None


def main():
    ap = argparse.ArgumentParser(description='Etiquetas con QR hacia las hojas de perforación de PB')
    ap.add_argument('pdf_pb', nargs='+', help='Uno o varios PDF de PB (p. ej. un closet por PDF)')
    ap.add_argument('csv_etiquetas')
    ap.add_argument('--salida', default='salida_qr')
    ap.add_argument('--enlaces', help='CSV archivo;url (enlaces de Drive)')
    ap.add_argument('--base-url', help='URL base si las hojas viven en un servicio propio')
    ap.add_argument('--demo', action='store_true', help='QR de prueba para validar impresión')
    ap.add_argument('--qr-mm', type=float, default=15)
    ap.add_argument('--formato', choices=['png', 'pdf'], default=FORMATO_HOJAS,
                    help='Formato de las hojas a subir (default: png)')
    ap.add_argument('--nombre', help='Nombre de la optimización (default: nombre del CSV)')
    args = ap.parse_args()

    nombre = args.nombre or re.sub(
        r'^Etiquetas\s*[-—_ ]+\s*', '',
        os.path.splitext(os.path.basename(args.csv_etiquetas))[0]).replace('_', ' ').strip()
    r = procesar([(os.path.basename(ruta), ruta) for ruta in args.pdf_pb],
                 decodificar(open(args.csv_etiquetas, 'rb').read()), nombre,
                 _resolver_urls(args), args.qr_mm, args.formato)
    s = r['resumen']
    if not s['hojas_pb'] or not s['etiquetas']:
        sys.exit('No se encontraron hojas de pieza en el PDF o etiquetas en el CSV.')

    carpeta = os.path.join(args.salida, 'hojas')
    os.makedirs(carpeta, exist_ok=True)
    for viejo in os.listdir(carpeta):
        os.remove(os.path.join(carpeta, viejo))
    for archivo, datos in r['hojas'].items():
        open(os.path.join(carpeta, archivo), 'wb').write(datos)
    with open(os.path.join(args.salida, 'reporte_match.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f, delimiter=';').writerows(r['reporte'])

    print(f"Hojas de pieza en PB:  {s['hojas_pb']}")
    print(f"Etiquetas de pieza:    {s['etiquetas']}  (+ {s['paneles']} de esquema)")
    esperadas = max(1, s['etiquetas'] - s['excluidas'])
    print(f"Enlazan:               {s['enlazan']} de {esperadas} ({s['enlazan'] / esperadas:.0%}), "
          f"{s['varias_hojas']} a varias hojas")
    print(f"Aproximadas:           {s['aproximadas']} (enlazaron sin nombre exacto; revisa el reporte)")
    print(f"Excluidas por regla:   {s['excluidas']} (su hoja de PB no trae operaciones: sin hoja ni QR)")
    print(f"Archivos a subir:      {s['archivos']} ({s['peso_kb'] / 1024:.1f} MB)")
    print(f"Sin enlace:            {len(s['sin_enlace'])} combinaciones")
    for x in s['sin_enlace']:
        print(f"  - {x['mueble']} / {x['tipo_pieza']}: {x['nota']}")
    for d in s['pdfs']:
        aviso = '' if d['etiquetas'] else '  <- ninguna etiqueta: ¿es de otro proyecto o de otra versión?'
        print(f"PDF {d['nombre']} ({d['proyecto']}): {d['etiquetas']} etiquetas{aviso}")
    if r['html']:
        ruta = os.path.join(args.salida, 'etiquetas_qr.html')
        open(ruta, 'w', encoding='utf-8').write(r['html'])
        print(f"Etiquetas con QR:      {s['con_qr']} -> {ruta}")
    else:
        print("Sin enlaces: solo se generaron hojas y reporte "
              "(usa --enlaces, --base-url o --demo para las etiquetas).")


if __name__ == '__main__':
    main()
