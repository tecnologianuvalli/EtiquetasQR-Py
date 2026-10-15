#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas del cruce etiqueta (Opticut) <-> hoja de perforación (PolyBoard).

    python test_cruce.py          (también corre con pytest)

Datos sintéticos: no hace falta PDF. Cubren la coincidencia exacta de siempre
y la aproximada (nombres acortados, sin acentos, abreviados o con errata), con
la regla que la hace segura: medidas iguales y una sola pieza posible; si no,
sin QR.
"""
import hashlib

import qr_etiquetas as q


def pb(pagina, mueble, ref, alto, ancho, maquinado=True, mat='PAN-LEG-LEG-MDP-2C-SAV-1830X...', esp=15, huella=None):
    # huella: texto de las operaciones; por defecto, distinta por pieza y medidas (no por mueble).
    return dict(pagina=pagina, mueble=mueble, ref=ref, alto=float(alto), ancho=float(ancho), esp=float(esp),
                maquinado=maquinado, mat=mat, huella=huella or f'{q.norm(ref)}/{alto}x{ancho}')


def et(mueble, tipo, largo, ancho, sku='PAN-LEG-LEG-MDP-2C-SAV-1830X2440-15-036', espesor=15):
    return dict(tipo='pieza', proyecto='Cocina 1', material='LEGNOLAM', mueble=mueble, tipo_pieza=tipo,
                largo=f'{largo:.2f}', ancho=f'{ancho:.2f}', medidas=f'{largo} × {ancho}', panelSKU=sku,
                espesor=f'{espesor:.2f}')


def unico(grupos):
    assert len(grupos) == 1, list(grupos)
    return next(iter(grupos.values()))


CAJONERO = 'GACAJ-3C-EXT-75-70-60-F15MM'
FRENTES = [
    pb(10, CAJONERO, 'Frente Cajon EXTENSIÓN Vista Lluvia (inferior)', 338, 356),
    pb(11, CAJONERO, 'Frente Cajon EXTENSIÓN Vista Lluvia (intermedio)', 153, 356),
    pb(12, CAJONERO, 'Frente Cajon EXTENSIÓN Vista Lluvia (superior)', 120, 356),
    pb(13, CAJONERO, 'Lateral Derecho', 700, 560),
    pb(14, CAJONERO, 'Lateral Izquierdo', 700, 560),
]


# --- La coincidencia exacta no cambia -----------------------------------------
def test_exacta_igual_que_siempre():
    g = unico(q.cruzar([et(CAJONERO, 'Frente Cajon EXTENSIÓN Vista Lluvia (inferior)', 338, 356)], FRENTES))
    assert g['paginas'] == [10] and not g['aproximada'] and g['nota'] == ''
    # Mismo nombre de archivo que antes: los QR ya impresos siguen sirviendo.
    esperado = hashlib.sha1(f"{q.norm(CAJONERO)}|{q.norm('Frente Cajon EXTENSIÓN Vista Lluvia (inferior)')}".encode()).hexdigest()[:8]
    assert g['codigo'] == esperado


def test_exacta_no_exige_medidas():
    # Con nombre exacto se enlaza aunque las medidas no coincidan (como antes).
    g = unico(q.cruzar([et(CAJONERO, 'Lateral Derecho', 699, 559)], FRENTES))
    assert g['paginas'] == [13] and not g['aproximada']


# --- El ejemplo: nombre acortado al exportar ---------------------------------
def test_nombre_acortado_enlaza_su_hoja():
    g = unico(q.cruzar([et(CAJONERO, 'Frente Cajon EXTENSION', 338, 356)], FRENTES))
    assert g['paginas'] == [10] and g['aproximada']
    assert 'Frente Cajon EXTENSIÓN Vista Lluvia (inferior)' in g['nota']
    assert q.reporte_filas({('x',): g}, [])[1][0] == 'OK (aproximado)'


def test_nombre_acortado_que_agrupa_variantes_se_reparte_por_medidas():
    items = [et(CAJONERO, 'Frente Cajon EXTENSION', 338, 356),
             et(CAJONERO, 'Frente Cajon EXTENSION', 153, 356),
             et(CAJONERO, 'Frente Cajon EXTENSION', 120, 356),
             et(CAJONERO, 'Frente Cajon EXTENSION', 338, 356)]
    grupos = q.cruzar(items, FRENTES)
    assert len(grupos) == 3
    assert [grupos[it['_grupo']]['paginas'] for it in items] == [[10], [11], [12], [10]]
    assert grupos[items[0]['_grupo']]['etiquetas'] == 2
    assert len({g['codigo'] for g in grupos.values()}) == 3      # un archivo por pieza de PB
    # Cada etiqueta del HTML recibe el QR de SU hoja.
    enlaces = {clave: f'https://drive.google.com/file/d/{g["codigo"]}/view' for clave, g in grupos.items()}
    html = q.generar_html_etiquetas('Lote', items, enlaces)
    assert html.count('class="et et-pieza et-qr"') == 4


def test_acentos_mayusculas_errata_y_abreviatura():
    for nombre in ['frente cajón extensión vista lluvia', 'Frente Cajon EXTENCION', 'Frente Caj EXT Vista']:
        g = unico(q.cruzar([et(CAJONERO, nombre, 338, 356)], FRENTES))
        assert g['paginas'] == [10] and g['aproximada'], nombre


def test_palabras_de_mas_en_el_csv():
    g = unico(q.cruzar([et(CAJONERO, 'Lateral Derecho Cajonero', 700, 560)], FRENTES))
    assert g['paginas'] == [13] and g['aproximada']


def test_partes_con_coma_aproximadas():
    g = unico(q.cruzar([et(CAJONERO, 'Lateral Der, Lateral Izq', 700, 560)], FRENTES))
    assert g['paginas'] == [13, 14] and g['aproximada']


# --- Nunca se adivina ----------------------------------------------------------
def test_aproximada_con_otras_medidas_no_enlaza():
    g = unico(q.cruzar([et(CAJONERO, 'Frente Cajon EXTENSION', 500, 356)], FRENTES))
    assert g['paginas'] == [] and not g['excluida'] and g['nota'].startswith('Parecida a')


def test_ambigua_si_dos_piezas_se_parecen_y_miden_igual():
    piezas = [pb(20, CAJONERO, 'Fondo Cajon IMPAZ CHICO Vista Ll...', 497.5, 299),
              pb(21, CAJONERO, 'Fondo Cajon IMPAZ GRANDE Vista ...', 497.5, 299)]
    g = unico(q.cruzar([et(CAJONERO, 'Fondo Cajon IMPAZ', 497.5, 299)], piezas))
    assert g['paginas'] == [] and g['nota'].startswith('Ambigua')


def test_el_tablero_desempata():
    piezas = [pb(30, CAJONERO, 'Fijo Esquinero Recto (blanco)', 751, 146, mat='PAN-SAB-KRO-MDP-2C-BLR-2070X...'),
              pb(31, CAJONERO, 'Fijo Esquinero Recto (color)', 751, 146, mat='PAN-LEG-LEG-MDP-2C-SAV-1830X...')]
    g = unico(q.cruzar([et(CAJONERO, 'Fijo Esquinero', 751, 146, sku='PAN-SAB-KRO-MDP-2C-BLR-2070X2800-15-003')], piezas))
    assert g['paginas'] == [30] and g['aproximada']


def test_numeros_y_codigos_exactos():
    piezas = [pb(40, CAJONERO, 'VISTA 120MM (15MM)', 850, 119), pb(41, CAJONERO, 'Puerta 15mm Alacena', 897, 396)]
    assert unico(q.cruzar([et(CAJONERO, 'VISTA 50-70MM', 850, 119)], piezas))['paginas'] == []
    assert unico(q.cruzar([et(CAJONERO, 'Puerta 15 Alacena', 897, 396)], piezas))['paginas'] == [41]
    assert unico(q.cruzar([et(CAJONERO, 'Puerta 1 Alacena', 897, 396)], piezas))['paginas'] == []


# --- Mueble aproximado ---------------------------------------------------------
def test_mueble_acortado():
    g = unico(q.cruzar([et('GACAJ-3C-EXT-75-70-60', 'Frente Cajon EXTENSIÓN Vista Lluvia (inferior)', 338, 356)], FRENTES))
    assert g['paginas'] == [10] and g['aproximada'] and CAJONERO in g['nota']


def test_mueble_aproximado_exige_medidas():
    g = unico(q.cruzar([et('GACAJ-3C-EXT', 'Lateral Derecho', 650, 560)], FRENTES))
    assert g['paginas'] == []


def test_mueble_ambiguo_lo_resuelven_las_medidas():
    piezas = FRENTES + [pb(50, 'GACAJ-3C-EXT-90-70-60-F15MM', 'Frente Cajon EXTENSIÓN Vista Lluvia (inferior)', 338, 506)]
    g = unico(q.cruzar([et('GACAJ-3C-EXT', 'Frente Cajon EXTENSION', 338, 506)], piezas))
    assert g['paginas'] == [50]
    g = unico(q.cruzar([et('GACAJ-3C-EXT', 'Frente Cajon EXTENSION', 338, 356)], piezas))
    assert g['paginas'] == [10]


def test_la_instancia_del_mueble_solo_se_cruza_si_las_piezas_lo_confirman():
    # Opticut y PB numeran distinto las instancias ([1],[2] vs. sin número,[1]):
    # el número no identifica; lo hacen las piezas (nombre + medidas).
    piezas = [pb(60, 'COSTADO-72-15-60[3]', 'PIEZA LIBRE COLOR', 948, 318)]
    g = unico(q.cruzar([et('COSTADO-72-15-60[2]', 'PIEZA LIBRE COLOR', 948, 318)], piezas))
    assert g['paginas'] == [60] and g['aproximada']
    g = unico(q.cruzar([et('COSTADO-72-15-60[2]', 'PIEZA LIBRE COLOR', 700, 318)], piezas))
    assert g['paginas'] == []


# --- Reglas que siguen igual ---------------------------------------------------
def test_excluida_aunque_sea_aproximada():
    piezas = [pb(70, CAJONERO, 'Estante Movil Cajonero', 560, 520, maquinado=False)]
    g = unico(q.cruzar([et(CAJONERO, 'Estante Movil', 560, 520)], piezas))
    assert g['excluida'] and g['paginas'] == [] and g['nota'].startswith('Excluida')


def test_pb_truncado_y_csv_acortado():
    piezas = [pb(80, CAJONERO, 'Trasera Cajon IMPAZ CHICO Vista L...', 299, 64.5),
              pb(81, CAJONERO, 'Trasera Cajon IMPAZ GRANDE Vista...', 298, 194.5)]
    items = [et(CAJONERO, 'Trasera Cajon IMPAZ', 299, 64.5), et(CAJONERO, 'Trasera Cajon IMPAZ', 298, 194.5)]
    grupos = q.cruzar(items, piezas)
    assert [grupos[it['_grupo']]['paginas'] for it in items] == [[80], [81]]


def test_parecido():
    assert q.parecido('Frente Cajon EXTENSION', 'Frente Cajón EXTENSIÓN Vista Lluvia (inferior)')
    assert q.parecido('GACAJ-3C-IMP-75-70-60', 'GACAJ-3C-IMP-75-70-60-F15MM')
    assert not q.parecido('Frente Cajon', 'Fondo Cajon')
    assert not q.parecido('COSTADO-72[2]', 'COSTADO-72[3]')
    assert not q.parecido('GACAJ-75', 'GACAJ-90')
    # Códigos con letras y números: exactos (3 cajones no es 2; 15 mm no es 18 mm).
    assert not q.parecido('GACAJ-3C-EXT', 'GACAJ-2C-EXT-75-70-60-F15MM')
    assert not q.parecido('Puerta F15MM', 'Puerta F18MM')


# --- Medidas del mueble editadas al exportar (lote FOTON) ---------------------
# En Opticut cambian los números del nombre del mueble ("ALMIC-2P-75-10" por
# "ALMIC-2P-91-70-30-F15MM"); el código (ALMIC-2P) no. El mueble de PB se elige
# por ese código y lo confirman sus piezas (nombre + medidas + espesor).
ALACENA = [pb(1, 'ALMIC-2P-91-70-30-F15MM', 'Techo', 670, 299), pb(2, 'ALMIC-2P-91-70-30-F15MM', 'Suelo', 669, 449),
           pb(3, 'ALMIC-2P-91-70-30-F15MM', 'Lateral Derecho', 789, 299), pb(4, 'ALMIC-2P-91-70-30-F15MM', 'Trasera', 869, 670)]


def test_mueble_con_las_medidas_del_nombre_editadas():
    items = [et('ALMIC-2P-75-10', 'Techo', 670, 299), et('ALMIC-2P-75-10', 'Trasera', 869, 670),
             et('ALMIC-2P-75-10', 'Lateral Derecho', 789, 299)]
    grupos = q.cruzar(items, ALACENA)
    assert [grupos[it['_grupo']]['paginas'] for it in items] == [[1], [4], [3]]
    assert all(g['aproximada'] for g in grupos.values())
    assert q._codigo_mueble('ALMIC-2P-91-70-30-F15MM') == q._codigo_mueble('ALMIC-2P-75-10') == ('ALMIC', '2P')
    assert q._codigo_mueble('GACAJ-3C-EXT-72-44') == ('GACAJ', '3C', 'EXT')


def test_otro_codigo_no_se_cruza():
    g = unico(q.cruzar([et('ALMIC-3P-75-10', 'Techo', 670, 299)], ALACENA))
    assert g['paginas'] == [] and g['nota'].startswith('Mueble no existe en PB')


def test_las_piezas_eligen_el_mueble_y_arrastran_las_genericas():
    # Mismo código, dos anchos: los laterales miden igual en ambos; el techo delata cuál es.
    piezas = [pb(10, 'GAPV-2P-72-70-60-F15MM', 'Lateral Derecho', 720, 560), pb(11, 'GAPV-2P-72-70-60-F15MM', 'Techo', 670, 560),
              pb(20, 'GAPV-2P-72-90-60-F15MM', 'Lateral Derecho', 720, 560), pb(21, 'GAPV-2P-72-90-60-F15MM', 'Techo', 870, 560)]
    items = [et('GAPV-2P-72-88', 'Lateral Derecho', 720, 560), et('GAPV-2P-72-88', 'Techo', 870, 560)]
    grupos = q.cruzar(items, piezas)
    assert [grupos[it['_grupo']]['paginas'] for it in items] == [[20], [21]]


def test_gemelos_identicos_se_reparten_en_orden():
    # Opticut los numera [1] y [2]; PB, sin número y [1]. Misma perforación hoja por hoja.
    piezas = [pb(30, 'ALPV-2P-91-70-30-F15MM', 'Techo', 720, 299, huella='op-techo'),
              pb(31, 'ALPV-2P-91-70-30-F15MM[1]', 'Techo', 720, 299, huella='op-techo')]
    items = [et('ALPV-2P-81-75 [1]', 'Techo', 720, 299), et('ALPV-2P-81-75 [2]', 'Techo', 720, 299)]
    grupos = q.cruzar(items, piezas)
    assert [grupos[it['_grupo']]['paginas'] for it in items] == [[30], [31]]


def test_muebles_iguales_por_fuera_pero_con_otra_perforacion_no_se_adivinan():
    piezas = [pb(40, 'ALPV-2P-91-70-30-F15MM', 'Puerta 15mm Alacena', 897, 396, huella='sin bisagra'),
              pb(41, 'ALPV-2P-91-70-30-F15MM[1]', 'Puerta 15mm Alacena', 897, 396, huella='con bisagra E D')]
    g = unico(q.cruzar([et('ALPV-2P-81-75', 'Puerta 15mm Alacena', 897, 396)], piezas))
    assert g['paginas'] == [] and g['nota'].startswith('Ambigua')


def test_el_mueble_elegido_debe_explicar_la_mitad_de_sus_piezas():
    items = [et('ALMIC-2P-75-10', 'Techo', 670, 299)] + [et('ALMIC-2P-75-10', f'Pieza rara {i}', 100 + i, 100) for i in range(3)]
    grupos = q.cruzar(items, ALACENA)
    assert all(g['paginas'] == [] for g in grupos.values())
    assert 'solo 1 de sus 4 piezas' in grupos[items[0]['_grupo']]['nota']


def test_opticut_redondea_medio_milimetro():
    piezas = [pb(50, 'ALMIC-2P-91-70-30-F15MM', 'Estante Fijo Piso', 670, 284.5)]
    g = unico(q.cruzar([et('ALMIC-2P-75-10', 'Estante Fijo Piso', 670, 284)], piezas))
    assert g['paginas'] == [50]


def test_otro_espesor_no_se_cruza():
    g = unico(q.cruzar([et('ALMIC-2P-75-10', 'Techo', 670, 299, espesor=18)], ALACENA))
    assert g['paginas'] == []


def test_nombre_de_pieza_que_solo_comparte_el_inicio():
    piezas = [pb(60, 'GACAJ-3C-EXT-72-70-60-F15MM', 'Fondo Cajon EXTENSIÓN Vista Lluvi...', 497.5, 299),
              pb(61, 'GACAJ-3C-EXT-72-70-60-F15MM', 'Lateral Derecho', 720, 560)]
    g = unico(q.cruzar([et('GACAJ-3C-EXT-72-44', 'Fondo Cajon EXTENSIÓN 50CM', 497.5, 299)], piezas))
    assert g['paginas'] == [60]
    assert q._mismo_arranque('Fondo Cajon EXTENSIÓN 50CM', 'Fondo Cajon EXTENSIÓN Vista Lluvi...')
    assert not q._mismo_arranque('Lateral Cajon EXTENSIÓN 50CM', 'Lateral Derecho')


if __name__ == '__main__':
    pruebas = [(n, f) for n, f in sorted(globals().items()) if n.startswith('test_') and callable(f)]
    fallos = 0
    for nombre, prueba in pruebas:
        try:
            prueba()
            print('  ok    ' + nombre)
        except Exception as e:      # noqa: BLE001 — se reporta y se sigue con las demás
            fallos += 1
            print(f'  FALLA {nombre}: {type(e).__name__} {e}')
    print(f'\n{len(pruebas) - fallos} de {len(pruebas)} pruebas ok.' if not fallos else f'\nFALLOS: {fallos}')
    raise SystemExit(1 if fallos else 0)
