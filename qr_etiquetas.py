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
    r'^(?P<ref>.+?)\s+(?P<mat>\S+)\s+Altura:\s*[\d.]+\s+Anchura:\s*[\d.]+\s+'
    r'Espesor:\s*[\d.]+\s+Cantidad:\s*\d+')
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


def leer_pb(pdf):
    """pdf: ruta o bytes. Devuelve [dict(pagina, mueble, ref, maquinado)]."""
    piezas, mueble_actual = [], None
    doc = pdfium.PdfDocument(pdf)
    try:
        for num in range(1, len(doc) + 1):
            texto = doc[num - 1].get_textpage().get_text_bounded() or ''
            lineas = [l.strip() for l in re.split(r'[\r\n]+', texto) if l.strip()]
            ini = next((i + 1 for i, l in enumerate(lineas[:6]) if RE_PAGINA.match(l)), None)
            if ini is None or len(lineas) <= ini + 1:
                continue
            cuerpo = lineas[ini:]
            m = RE_PIEZA.match(cuerpo[1])
            if m:
                # El mueble en la hoja de pieza puede venir truncado ("...F1...");
                # se usa el nombre completo de la portada si es consistente.
                mueble = cuerpo[0]
                if mueble_actual and norm(mueble_actual).startswith(norm(_sin_puntos(mueble))):
                    mueble = mueble_actual
                maquinado = lleva_trabajo(cuerpo[2:])
                piezas.append(dict(pagina=num, mueble=mueble, ref=m.group('ref').strip(),
                                   maquinado=maquinado))
            elif re.match(r'^Altura\s+[\d.]+\s*mm', cuerpo[1]):
                mueble_actual = cuerpo[0]       # portada de mueble
    finally:
        doc.close()
    return piezas


# ============================================================================
# 3) Cruce mueble + tipo de pieza
# ============================================================================
def cruzar(items, piezas_pb):
    """OrderedDict[(mueble, tipo_pieza)] -> dict(paginas, etiquetas, nota, codigo, excluida)."""
    por_mueble = defaultdict(list)
    for p in piezas_pb:
        por_mueble[norm(p['mueble'])].append(p)
    nombres_pb = {norm(p['mueble']): p['mueble'] for p in piezas_pb}

    grupos = OrderedDict()
    for it in items:
        if it['tipo'] != 'pieza':
            continue
        g = grupos.setdefault((it['mueble'], it['tipo_pieza']),
                              dict(paginas=[], etiquetas=0, nota='', codigo='', excluida=False))
        g['etiquetas'] += 1

    for (mueble, ref), g in grupos.items():
        g['codigo'] = hashlib.sha1(f'{norm(mueble)}|{norm(ref)}'.encode()).hexdigest()[:8]
        candidatas = por_mueble.get(norm(mueble))
        if not candidatas:
            cerca = difflib.get_close_matches(norm(mueble), list(nombres_pb), n=1, cutoff=0.8)
            g['nota'] = 'Mueble no existe en PB' + (f' (¿será {nombres_pb[cerca[0]]}?)' if cerca else '')
            continue
        paginas = []
        # "Lateral Derecho, Lateral Izquierdo" -> se busca cada parte
        for parte in [x.strip() for x in ref.split(',') if x.strip()]:
            n_parte = norm(parte)
            for p in candidatas:
                n_pb = norm(_sin_puntos(p['ref']))
                if (n_pb == n_parte or (_truncado(p['ref']) and n_parte.startswith(n_pb))) \
                        and p['pagina'] not in paginas:
                    paginas.append(p['pagina'])
        if not paginas:
            cerca = difflib.get_close_matches(ref, sorted({p['ref'] for p in candidatas}), n=1, cutoff=0.7)
            g['nota'] = 'Tipo de pieza no existe en ese mueble' + (f' (¿será {cerca[0]}?)' if cerca else '')
            continue
        # Ninguna de sus hojas lleva trabajo: sin hoja y sin QR. Si al menos una
        # lleva, se conservan todas (p. ej. par de puertas), para que el
        # perforador vea cuál sí y cuál no. El día que PB agregue operaciones a
        # una pieza hoy excluida, entra sola: no hay nada que actualizar aquí.
        con_trabajo = {p['pagina'] for p in candidatas if p['maquinado']}
        if not con_trabajo.intersection(paginas):
            g['excluida'] = True
            g['nota'] = ('Excluida: su hoja de PB no trae operaciones (pág. ' +
                         ' '.join(map(str, sorted(paginas))) + ')')
            continue
        g['paginas'] = sorted(paginas)
    return grupos


_PALETA_16_GRISES = sum(([v * 17] * 3 for v in range(16)), [])


def _png_de_paginas(doc, paginas):
    """Una sola imagen PNG con las páginas apiladas, en 16 tonos de gris
    (paleta fija de 4 bits: liviana y rápida de generar)."""
    imgs = [doc[n - 1].render(scale=PNG_DPI / 72, grayscale=True).to_pil() for n in paginas]
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


def generar_hojas(pdf, grupos, formato=None):
    """Devuelve {'<codigo>.<ext>': bytes} con las hojas de cada grupo enlazado.
    pdf: ruta o bytes."""
    formato = formato or FORMATO_HOJAS
    salida = {}
    if formato == 'png':
        doc = pdfium.PdfDocument(pdf)
        for g in grupos.values():
            if g['paginas']:
                salida[g['codigo'] + '.png'] = _png_de_paginas(doc, g['paginas'])
        doc.close()
        return salida
    lector = PdfReader(io.BytesIO(pdf) if isinstance(pdf, (bytes, bytearray)) else pdf)
    for (mueble, ref), g in grupos.items():
        if not g['paginas']:
            continue
        w = PdfWriter()
        for n in g['paginas']:
            w.add_page(lector.pages[n - 1])
        w.add_metadata({'/Title': f'{mueble} — {ref}'})
        buf = io.BytesIO()
        w.write(buf)
        salida[g['codigo'] + '.pdf'] = buf.getvalue()
    return salida


def reporte_filas(grupos, piezas_pb, ext='png'):
    usadas = {n for g in grupos.values() for n in g['paginas']}
    filas = [['estado', 'mueble', 'tipo_pieza', 'etiquetas', 'hojas', 'paginas_PB', 'archivo', 'nota']]
    for (mueble, ref), g in grupos.items():
        n = len(g['paginas'])
        estado = ('EXCLUIDA' if g['excluida'] else 'SIN ENLACE') if n == 0 else ('OK' if n == 1 else 'OK (varias hojas)')
        filas.append([estado, mueble, ref, g['etiquetas'], n, ' '.join(map(str, g['paginas'])),
                      f"{g['codigo']}.{ext}" if n else '', g['nota']])
    # Hojas de PB con operaciones que ninguna etiqueta usa.
    for p in piezas_pb:
        if p['pagina'] not in usadas and p['maquinado']:
            filas.append(['PB SIN ETIQUETA', p['mueble'], p['ref'], 0, 1, p['pagina'], '',
                          'Hoja de PB que ninguna etiqueta usa'])
    return filas


# ============================================================================
# 4) HTML de etiquetas — port de generarHTMLEtiquetas() + QR
# ============================================================================
def _esc(v):
    return html.escape(str(v if v is not None else ''), quote=True)


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
    """enlaces: {(mueble, tipo_pieza): url}. Sin enlace, la etiqueta sale
    exactamente como la de la WebApp."""
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
        url = enlaces.get((it['mueble'], it['tipo_pieza']))
        if not url:
            return ('<div class="et et-pieza">'
                    f'<div class="l fuerte">{nombre}</div>'
                    f'<div class="l inv">{_esc(it["proyecto"])}</div>'
                    f'<div class="l mat">{_esc(it["material"])}</div>'
                    f'<div class="l mueble">{_esc(it["mueble"])}</div>'
                    f'<div class="l inv">{_esc(it["tipo_pieza"])}</div>'
                    f'<div class="l medidas">{_esc(it["medidas"])}</div>'
                    '</div>')
        n_qr += 1
        return ('<div class="et et-pieza et-qr"><div class="txt">' +
                _linea('fuerte', nombre_opti or '', 8, True, ancho_txt) +
                _linea('inv', it['proyecto'], 8.5, True, ancho_inv) +
                _linea('mat', it['material'], 6.5, False, ancho_txt) +
                _linea('mueble', it['mueble'], 8.5, True, ancho_txt, dos_lineas=True) +
                _linea('inv', it['tipo_pieza'], 8.5, True, ancho_inv, dos_lineas=True) +
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
    """pdf_pb: ruta o bytes. url_de: función archivo ('<codigo>.<ext>') -> url
    (o None para no generar etiquetas). Devuelve dict con grupos, hojas, reporte, html, resumen."""
    piezas_pb = leer_pb(pdf_pb)
    parse = parsear_etiquetas_opticut(csv_texto)
    grupos = cruzar(parse['items'], piezas_pb)
    formato = formato or FORMATO_HOJAS
    # con_hojas=False ahorra el trabajo de partir el PDF cuando solo se
    # necesita el HTML (segunda llamada de la API).
    hojas = generar_hojas(pdf_pb, grupos, formato) if con_hojas else {}

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
            con_qr=sum(g['etiquetas'] for c, g in grupos.items() if c in enlaces),
            excluidas=sum(g['etiquetas'] for g in grupos.values() if g['excluida']),
            sin_enlace=[dict(mueble=m, tipo_pieza=r, nota=g['nota'])
                        for (m, r), g in grupos.items() if not g['paginas'] and not g['excluida']]))


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
    ap.add_argument('pdf_pb')
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
    r = procesar(args.pdf_pb, decodificar(open(args.csv_etiquetas, 'rb').read()), nombre,
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
    print(f"Excluidas por regla:   {s['excluidas']} (su hoja de PB no trae operaciones: sin hoja ni QR)")
    print(f"Archivos a subir:      {s['archivos']} ({s['peso_kb'] / 1024:.1f} MB)")
    print(f"Sin enlace:            {len(s['sin_enlace'])} combinaciones")
    for x in s['sin_enlace']:
        print(f"  - {x['mueble']} / {x['tipo_pieza']}: {x['nota']}")
    if r['html']:
        ruta = os.path.join(args.salida, 'etiquetas_qr.html')
        open(ruta, 'w', encoding='utf-8').write(r['html'])
        print(f"Etiquetas con QR:      {s['con_qr']} -> {ruta}")
    else:
        print("Sin enlaces: solo se generaron hojas y reporte "
              "(usa --enlaces, --base-url o --demo para las etiquetas).")


if __name__ == '__main__':
    main()
