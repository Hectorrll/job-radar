"""Evalua una vacante con un modelo de IA de NVIDIA (gratis, OpenAI-compatible).

Modelo principal: Qwen3.5-122B (MoE 10B activos, mejor espanol del catalogo, rapido,
no-"thinking"). Si falla o NVIDIA lo deprecia, cae a un FALLBACK probado (Llama 3.3 70B).
El ID se puede cambiar sin tocar codigo con la env var RADAR_MODEL.

Robustez (el free tier de NVIDIA = 40 RPM GLOBAL por key, no ampliable):
- Limitador de ritmo (throttle) compartido entre hilos: arranca como mucho 1 request
  cada RADAR_MIN_INTERVAL seg -> se mantiene por debajo de 40 RPM aunque evaluemos
  MUCHAS vacantes por corrida. Asi podemos subir el volumen sin que NVIDIA nos corte.
- Backoff ante 429 / 5xx (respeta Retry-After si viene).
- Sesion HTTP reutilizada (connection pooling) = mas rapido.
- Parseo defensivo del JSON; ante cualquier fallo -> no aceptar + log, nunca rompe.
"""
import os
import json
import time
import threading

import requests

NVIDIA_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Principal (mejor espanol) + fallback probado. RADAR_MODEL permite cambiar sin editar codigo.
MODEL = os.getenv("RADAR_MODEL", "qwen/qwen3.5-122b-a10b")
FALLBACK_MODEL = "meta/llama-3.3-70b-instruct"

REQ_TIMEOUT = int(os.getenv("RADAR_REQ_TIMEOUT", "60"))  # bajado de 120: una respuesta colgada falla rapido y no estanca la corrida
MAX_TOKENS = 200
# Ritmo: 1 request cada 1.6s ~= 37 RPM, debajo del techo de 40 (margen de seguridad).
# Subilo (ej. 2.5) si corres Hermes/n8n en paralelo sobre la MISMA key: el limite de 40
# es GLOBAL por key, asi que todo lo que use la key suma.
MIN_INTERVAL = float(os.getenv("RADAR_MIN_INTERVAL", "1.6"))

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()

_session = requests.Session()

# --- Limitador de ritmo compartido entre hilos (reserva de turnos) ---
_rate_lock = threading.Lock()
_next_slot = [0.0]


def _throttle():
    """Reserva el proximo turno de envio para no superar ~1/MIN_INTERVAL requests/seg.
    Cada hilo toma un turno futuro y duerme hasta el; los arranques quedan espaciados."""
    with _rate_lock:
        now = time.monotonic()
        start_at = max(now, _next_slot[0])
        _next_slot[0] = start_at + MIN_INTERVAL
        wait = start_at - now
    if wait > 0:
        time.sleep(wait)


class _Retryable(Exception):
    """Error transitorio (429 / 5xx) que conviene reintentar con espera."""
    def __init__(self, msg, wait=None):
        super().__init__(msg)
        self.wait = wait


def _pedir(prompt, modelo):
    """Una llamada al modelo (pasando por el throttle). Devuelve el texto, o lanza."""
    payload = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Accept": "application/json"}
    _throttle()
    r = _session.post(URL, headers=headers, json=payload, timeout=REQ_TIMEOUT)
    if r.status_code == 429:
        ra = r.headers.get("Retry-After", "")
        raise _Retryable("HTTP 429 rate limit", wait=float(ra) if ra.isdigit() else None)
    if r.status_code >= 500:
        raise _Retryable(f"HTTP {r.status_code} servidor")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def evaluar_vacante(v):
    """Devuelve {'aceptar': bool, 'motivo': str}. Nunca rompe el radar.
    Prueba MODEL; ante 429/5xx hace backoff; si el modelo sigue fallando, cae a FALLBACK."""
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\n"
        f"Empresa: {v['empresa']}\n"
        f"Ubicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\n"
        f"Descripcion: {v['descripcion']}"
    )
    modelos = [MODEL] if MODEL == FALLBACK_MODEL else [MODEL, FALLBACK_MODEL]
    ultimo_error = ""
    for idx, modelo in enumerate(modelos):
        if idx > 0:  # el modelo principal fallo -> avisamos que caemos al fallback
            print(f"# INFO fallback -> {modelo}: '{v['titulo'][:35]}' ({ultimo_error[:50]})")
        backoff = 2.0
        for intento in range(2):
            try:
                content = _pedir(prompt, modelo)
                ini, fin = content.find("{"), content.rfind("}")
                if ini == -1 or fin == -1:
                    ultimo_error = "respuesta sin JSON"
                    continue
                res = json.loads(content[ini:fin + 1])
                return {"aceptar": bool(res.get("aceptar")), "motivo": str(res.get("motivo", ""))[:300]}
            except _Retryable as e:
                ultimo_error = str(e)
                time.sleep(e.wait if e.wait else backoff)
                backoff = min(backoff * 2, 30)
            except Exception as e:
                ultimo_error = str(e)
                time.sleep(1)
    print(f"# WARN evaluar '{v['titulo'][:40]}': {ultimo_error}")
    return {"aceptar": False, "motivo": f"error: {ultimo_error}"}
