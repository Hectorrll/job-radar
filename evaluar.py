"""Evalua una vacante con un modelo de IA de NVIDIA (gratis, OpenAI-compatible).

Modelo principal: Llama 4 Maverick (meta/llama-4-maverick-17b-128e-instruct) -- el mejor que
FUNCIONA A ESCALA: 9/10 en el eval golden-set, rapido, occidental, y CONFIABLE con 100+ evals/corrida.
Kimi K2.6 gano el eval por calidad (10/10) PERO a ESCALA da HTTP 429 ~79% (el free tier throttlea
los modelos pesados/1T bajo volumen) -> desperdicia la API; sirve solo para lotes chicos. Lo mismo
le pasaria a DeepSeek-V4-Pro / MiniMax (tambien 10/10 pero pesados). Fallback: Llama 3.3 70B (confiable).
Descartados antes: Qwen=timeout68%, Scout=404. Cambiar sin codigo: env RADAR_MODEL.
Leccion: la CALIDAD se mide con golden set, pero la ELECCION exige probar A ESCALA (fallback count en
una corrida de 100+): los mejores razonadores se rate-limitan con volumen.

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

# Hasta 4 keys: NVIDIA_API_KEY [+ _2] [+ _3] [+ _4] (Hector + mama + primo + tio). Round-robin
# -> cada key conserva su ~38 RPM => 2=~76, 3=~114, 4=~152 RPM combinados.
KEYS = [k for k in [os.getenv("NVIDIA_API_KEY"), os.getenv("NVIDIA_API_KEY_2"),
                    os.getenv("NVIDIA_API_KEY_3"), os.getenv("NVIDIA_API_KEY_4")] if k]
if not KEYS:
    raise SystemExit("# ERROR: falta NVIDIA_API_KEY")
URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Principal: Llama 4 Maverick (CONFIABLE A ESCALA: 9/10 en el eval + maneja 100+ evals sin 429,
# rapido, occidental, eficiente con la API). Kimi K2.6 ganaba en calidad (10/10) PERO da 429 ~79%
# a volumen -> desperdicia la API. Fallback: Llama 3.3 70B. Cambiar sin codigo: env RADAR_MODEL.
MODEL = os.getenv("RADAR_MODEL", "meta/llama-4-maverick-17b-128e-instruct")
FALLBACK_MODEL = "meta/llama-3.3-70b-instruct"

REQ_TIMEOUT = int(os.getenv("RADAR_REQ_TIMEOUT", "60"))  # bajado de 120: una respuesta colgada falla rapido y no estanca la corrida
MAX_TOKENS = 350  # margen para que modelos que razonan (Kimi) terminen el JSON sin cortarse
# Ritmo: 1 request cada 1.6s ~= 37 RPM, debajo del techo de 40 (margen de seguridad).
# Subilo (ej. 2.5) si corres Hermes/n8n en paralelo sobre la MISMA key: el limite de 40
# es GLOBAL por key, asi que todo lo que use la key suma.
MIN_INTERVAL = float(os.getenv("RADAR_MIN_INTERVAL", "1.6"))

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()

_session = requests.Session()

# --- Limitador de ritmo POR KEY (cada key tiene su propio presupuesto de ~38 RPM) ---
# Las llamadas se reparten round-robin entre las keys; con 2 keys el throughput se duplica.
_key_locks = [threading.Lock() for _ in KEYS]
_key_next = [[0.0] for _ in KEYS]
_rr_lock = threading.Lock()
_rr = [0]


def _pick_key():
    """Round-robin: indice de la proxima key a usar."""
    with _rr_lock:
        i = _rr[0] % len(KEYS)
        _rr[0] += 1
    return i


def _throttle(i):
    """Reserva el proximo turno de la key i (no pasar ~1/MIN_INTERVAL req/seg POR KEY)."""
    with _key_locks[i]:
        now = time.monotonic()
        start_at = max(now, _key_next[i][0])
        _key_next[i][0] = start_at + MIN_INTERVAL
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
    i = _pick_key()
    headers = {"Authorization": f"Bearer {KEYS[i]}", "Accept": "application/json"}
    _throttle(i)
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
