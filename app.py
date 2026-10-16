# -*- coding: utf-8 -*-
"""
app.py — API del servicio de etiquetas con QR (Render Web Service).

  GET  /salud       -> {"ok": true}   (sirve para despertar el servicio)
  POST /procesar    -> hojas de perforación partidas + reporte del cruce
  POST /etiquetas   -> HTML de etiquetas con los QR ya puestos

Todas las llamadas (menos /salud) llevan el header X-API-Key. La clave se lee
de la variable de entorno API_KEY (también se acepta APY_KEY); nunca va en el
código ni en el repositorio.

Uno o varios PDF de PolyBoard: un corte por nivel junta varios prototipos (p. ej.
tres closets) y cada uno es un proyecto de PB con su PDF. Van en los campos
`pdf_pb`, `pdf_pb_2`, `pdf_pb_3`… (o `pdf_pb` repetido).

Arranque en Render:
  Build command:  pip install -r requirements.txt
  Start command:  uvicorn app:app --host 0.0.0.0 --port $PORT

El servicio no guarda nada entre llamadas: por eso /etiquetas recibe otra vez
los PDF y el CSV junto con los enlaces.
"""
import base64
import hmac
import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

import qr_etiquetas as qr

MAX_BYTES = 30 * 1024 * 1024          # tope por archivo subido
MAX_PDFS = 12                         # PDF de PB por llamada (prototipos de un nivel)
MIME = {'png': 'image/png', 'pdf': 'application/pdf'}

app = FastAPI(title='Nuvalli — etiquetas con QR', docs_url=None, redoc_url=None)


def verificar_clave(x_api_key: str = Header(default='')):
    esperada = os.environ.get('API_KEY') or os.environ.get('APY_KEY') or ''
    if not esperada:
        raise HTTPException(500, 'El servicio no tiene configurada la variable API_KEY.')
    if not hmac.compare_digest(x_api_key.encode(), esperada.encode()):
        raise HTTPException(401, 'X-API-Key inválida o ausente.')


async def _leer(archivo: UploadFile, nombre: str) -> bytes:
    datos = await archivo.read()
    if not datos:
        raise HTTPException(400, f'El archivo {nombre} llegó vacío.')
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, f'El archivo {nombre} supera {MAX_BYTES // 1024 // 1024} MB.')
    return datos


async def _formulario(request: Request):
    """PDF de PB (pdf_pb, pdf_pb_2…), CSV y los demás campos del multipart."""
    form = await request.form()
    pdfs, csv_bytes, campos = [], None, {}
    for clave, valor in form.multi_items():
        if isinstance(valor, UploadFile):
            if clave == 'pdf_pb' or clave.startswith('pdf_pb_'):
                datos = await _leer(valor, clave)
                if not datos.lstrip().startswith(b'%PDF'):
                    raise HTTPException(400, f'{clave} no es un PDF.')
                pdfs.append((valor.filename or clave, datos))
            elif clave == 'csv_etiquetas':
                csv_bytes = await _leer(valor, clave)
        else:
            campos[clave] = valor
    if not pdfs:
        raise HTTPException(400, 'Falta el PDF de PolyBoard (pdf_pb).')
    if len(pdfs) > MAX_PDFS:
        raise HTTPException(400, f'Máximo {MAX_PDFS} PDF de PolyBoard por llamada.')
    if csv_bytes is None:
        raise HTTPException(400, 'Falta el CSV de etiquetas (csv_etiquetas).')
    return pdfs, csv_bytes, campos


def _procesar(pdfs, csv_bytes: bytes, nombre: str, url_de, qr_mm: float, formato: str,
              con_hojas: bool = True):
    if formato not in MIME:
        raise HTTPException(400, "formato debe ser 'png' o 'pdf'.")
    try:
        r = qr.procesar(pdfs, qr.decodificar(csv_bytes), nombre, url_de, qr_mm, formato, con_hojas)
    except HTTPException:
        raise
    except Exception as e:                                   # PDF dañado, etc.
        raise HTTPException(422, f'No se pudo procesar: {type(e).__name__}: {e}')
    vacios = [d['nombre'] for d in r['resumen']['pdfs'] if not d['hojas_pb']]
    if vacios:
        raise HTTPException(422, 'El PDF no contiene hojas de pieza de PolyBoard.' if len(pdfs) == 1 else
                            f'Sin hojas de pieza de PolyBoard: {", ".join(vacios)}.')
    if not r['resumen']['etiquetas']:
        raise HTTPException(422, 'El CSV no contiene etiquetas de pieza de Opticut.')
    return r


@app.get('/salud')
def salud():
    return {'ok': True}


@app.post('/procesar', dependencies=[Depends(verificar_clave)])
async def procesar(request: Request):
    """Paso 1: cruza y devuelve las hojas para que GAS las suba a Drive."""
    pdfs, csv_bytes, campos = await _formulario(request)
    formato = campos.get('formato') or qr.FORMATO_HOJAS
    # El trabajo pesado va en un hilo aparte: /salud sigue respondiendo mientras tanto.
    r = await run_in_threadpool(_procesar, pdfs, csv_bytes, campos.get('nombre', ''), None, 15, formato)
    return {
        'resumen': r['resumen'],
        'reporte': r['reporte'],
        'hojas': [{'archivo': archivo, 'mime': MIME[formato],
                   'base64': base64.b64encode(datos).decode('ascii')}
                  for archivo, datos in r['hojas'].items()],
    }


@app.post('/etiquetas', dependencies=[Depends(verificar_clave)])
async def etiquetas(request: Request):
    """Paso 2: con los enlaces de Drive ({archivo: url}) devuelve el HTML con QR.
    Una hoja sin enlace en el mapa sale sin QR (etiqueta idéntica a la actual)."""
    pdfs, csv_bytes, campos = await _formulario(request)
    try:
        mapa = json.loads(campos['enlaces'])
        assert isinstance(mapa, dict)
    except Exception:
        raise HTTPException(400, 'enlaces debe ser un JSON {"archivo": "url"}.')
    mapa = {str(k): str(v) for k, v in mapa.items() if str(v).lower().startswith('http')}
    try:
        qr_mm = float(campos.get('qr_mm') or 15)
    except ValueError:
        raise HTTPException(400, 'qr_mm debe ser un número.')
    if not 8 <= qr_mm <= 20:
        raise HTTPException(400, 'qr_mm debe estar entre 8 y 20.')
    formato = campos.get('formato') or qr.FORMATO_HOJAS
    r = await run_in_threadpool(_procesar, pdfs, csv_bytes, campos.get('nombre', ''), mapa.get, qr_mm, formato, False)
    return {'resumen': r['resumen'], 'html': r['html']}
