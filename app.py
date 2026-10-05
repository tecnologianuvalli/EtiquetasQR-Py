# -*- coding: utf-8 -*-
"""
app.py — API del servicio de etiquetas con QR (Render Web Service).

  GET  /salud       -> {"ok": true}   (sirve para despertar el servicio)
  POST /procesar    -> hojas de perforación partidas + reporte del cruce
  POST /etiquetas   -> HTML de etiquetas con los QR ya puestos

Todas las llamadas (menos /salud) llevan el header X-API-Key. La clave se lee
de la variable de entorno API_KEY (también se acepta APY_KEY); nunca va en el
código ni en el repositorio.

Arranque en Render:
  Build command:  pip install -r requirements.txt
  Start command:  uvicorn app:app --host 0.0.0.0 --port $PORT

El servicio no guarda nada entre llamadas: por eso /etiquetas recibe otra vez
el PDF y el CSV junto con los enlaces.
"""
import base64
import hmac
import json
import os

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

import qr_etiquetas as qr

MAX_BYTES = 30 * 1024 * 1024          # tope por archivo subido
MIME = {'png': 'image/png', 'pdf': 'application/pdf'}

app = FastAPI(title='Nuvalli — etiquetas con QR', docs_url=None, redoc_url=None)


def verificar_clave(x_api_key: str = Header(default='')):
    esperada = os.environ.get('API_KEY') or os.environ.get('APY_KEY') or ''
    if not esperada:
        raise HTTPException(500, 'El servicio no tiene configurada la variable API_KEY.')
    if not hmac.compare_digest(x_api_key.encode(), esperada.encode()):
        raise HTTPException(401, 'X-API-Key inválida o ausente.')


def _leer(archivo: UploadFile, nombre: str) -> bytes:
    datos = archivo.file.read()
    if not datos:
        raise HTTPException(400, f'El archivo {nombre} llegó vacío.')
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, f'El archivo {nombre} supera {MAX_BYTES // 1024 // 1024} MB.')
    return datos


def _procesar(pdf: bytes, csv_bytes: bytes, nombre: str, url_de, qr_mm: float, formato: str,
              con_hojas: bool = True):
    if formato not in MIME:
        raise HTTPException(400, "formato debe ser 'png' o 'pdf'.")
    if not pdf.lstrip().startswith(b'%PDF'):
        raise HTTPException(400, 'pdf_pb no es un PDF.')
    try:
        r = qr.procesar(pdf, qr.decodificar(csv_bytes), nombre, url_de, qr_mm, formato, con_hojas)
    except HTTPException:
        raise
    except Exception as e:                                   # PDF dañado, etc.
        raise HTTPException(422, f'No se pudo procesar: {type(e).__name__}: {e}')
    if not r['resumen']['hojas_pb']:
        raise HTTPException(422, 'El PDF no contiene hojas de pieza de PolyBoard.')
    if not r['resumen']['etiquetas']:
        raise HTTPException(422, 'El CSV no contiene etiquetas de pieza de Opticut.')
    return r


@app.get('/salud')
def salud():
    return {'ok': True}


@app.post('/procesar', dependencies=[Depends(verificar_clave)])
def procesar(pdf_pb: UploadFile = File(...), csv_etiquetas: UploadFile = File(...),
             nombre: str = Form(''), formato: str = Form(qr.FORMATO_HOJAS)):
    """Paso 1: cruza y devuelve las hojas para que GAS las suba a Drive."""
    r = _procesar(_leer(pdf_pb, 'pdf_pb'), _leer(csv_etiquetas, 'csv_etiquetas'),
                  nombre, None, 15, formato)
    return {
        'resumen': r['resumen'],
        'reporte': r['reporte'],
        'hojas': [{'archivo': archivo, 'mime': MIME[formato],
                   'base64': base64.b64encode(datos).decode('ascii')}
                  for archivo, datos in r['hojas'].items()],
    }


@app.post('/etiquetas', dependencies=[Depends(verificar_clave)])
def etiquetas(pdf_pb: UploadFile = File(...), csv_etiquetas: UploadFile = File(...),
              enlaces: str = Form(...), nombre: str = Form(''),
              formato: str = Form(qr.FORMATO_HOJAS), qr_mm: float = Form(15)):
    """Paso 2: con los enlaces de Drive ({archivo: url}) devuelve el HTML con QR.
    Una hoja sin enlace en el mapa sale sin QR (etiqueta idéntica a la actual)."""
    try:
        mapa = json.loads(enlaces)
        assert isinstance(mapa, dict)
    except Exception:
        raise HTTPException(400, 'enlaces debe ser un JSON {"archivo": "url"}.')
    mapa = {str(k): str(v) for k, v in mapa.items() if str(v).lower().startswith('http')}
    if not 8 <= qr_mm <= 20:
        raise HTTPException(400, 'qr_mm debe estar entre 8 y 20.')
    r = _procesar(_leer(pdf_pb, 'pdf_pb'), _leer(csv_etiquetas, 'csv_etiquetas'),
                  nombre, mapa.get, qr_mm, formato, con_hojas=False)
    return {'resumen': r['resumen'], 'html': r['html']}
