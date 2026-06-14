"""Evalua vacantes con modelos de IA de NVIDIA (gratis, OpenAI-compatible). DOS NIVELES:

NIVEL 1 (screening, rapido y confiable): Llama 4 Maverick en el pool "fast" (NVIDIA_API_KEY
[+ _2 .. _4]), ~38 RPM por key. Evalua TODAS las vacantes -> acepta/descarta. Fallback Llama 3.3 70B.

NIVEL 2 (lectura PROFUNDA, opcional): Kimi K2.6 (fallback MiniMax M3) en el pool "think"
(NVIDIA_API_KEY_5 [+ _6], dedicado). SOLO re-juzga los matches que el Nivel 1 ACEPTO -> da un
motivo mas profundo / 2da opinion. Throttle BAJO (RADAR_THINK_INTERVAL) para no gatillar 429 en
los modelos pesados. Si NO hay keys 5/6, el Nivel 2 se omite (el radar funciona igual con Nivel 1).

Por que asi: los thinking (Kimi/DeepSeek) ganaron en calidad (10/10 en el eval golden-set) PERO
dan 429 a escala; usandolos solo en los POCOS aceptados + keys dedicadas + throttle bajo, rinden
sin 429. (Historia: Qwen3.5=timeout68%, Llama-4-Scout=404/VLM -> descartados como principal.)
"""
import os
import json
import time
import threading

import requests


def _keys(*names):
    return [k for k in (os.getenv(n) for n in names) if k]


KEYS_FAST = _keys("NVIDIA_API_KEY", "NVIDIA_API_KEY_2", "NVIDIA_API_KEY_3", "NVIDIA_API_KEY_4")
KEYS_THINK = _keys("NVIDIA_API_KEY_5", "NVIDIA_API_KEY_6")
if not KEYS_FAST:
    raise SystemExit("# ERROR: falta NVIDIA_API_KEY")

URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Nivel 1 (screener): rapido y confiable a escala.
MODEL = os.getenv("RADAR_MODEL", "meta/llama-4-maverick-17b-128e-instruct")
FALLBACK_MODEL = "meta/llama-3.3-70b-instruct"
# Nivel 2 (juez profundo): Kimi K2.6 primario (10/10 + rápido + confiable en el eval golden-set).
# Fallback = MiniMax M3 (9/10, razona excelente): reemplazó a DeepSeek V4 Pro, que quedó roto/flaky
# en NVIDIA (1/10, timeouts de conexión) — verificado 2026-06-13 con comparar_modelos.py.
THINK_MODEL = os.getenv("RADAR_THINK_MODEL", "moonshotai/kimi-k2.6")
THINK_FALLBACK = os.getenv("RADAR_THINK_FALLBACK", "minimaxai/minimax-m3")

REQ_TIMEOUT = int(os.getenv("RADAR_REQ_TIMEOUT", "60"))
MAX_TOKENS = 350
THINK_MAX_TOKENS = 500            # los thinking necesitan mas espacio para razonar + emitir JSON
MIN_INTERVAL = float(os.getenv("RADAR_MIN_INTERVAL", "1.6"))       # por key fast  (~38 RPM)
THINK_INTERVAL = float(os.getenv("RADAR_THINK_INTERVAL", "3.0"))   # por key think (~20 RPM, evita 429)

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()

_session = requests.Session()


class _Retryable(Exception):
    """Error transitorio (429 / 5xx) que conviene reintentar con espera."""
    def __init__(self, msg, wait=None):
        super().__init__(msg)
        self.wait = wait


class _Pool:
    """Pool de keys con round-robin + throttle POR KEY (cada key respeta su propio intervalo)."""
    def __init__(self, keys, interval):
        self.keys = keys
        self.interval = interval
        self._locks = [threading.Lock() for _ in keys]
        self._next = [[0.0] for _ in keys]
        self._rr_lock = threading.Lock()
        self._rr = [0]

    def _acquire(self):
        with self._rr_lock:
            i = self._rr[0] % len(self.keys)
            self._rr[0] += 1
        with self._locks[i]:
            now = time.monotonic()
            start_at = max(now, self._next[i][0])
            self._next[i][0] = start_at + self.interval
            wait = start_at - now
        if wait > 0:
            time.sleep(wait)
        return self.keys[i]

    def pedir(self, prompt, modelo, max_tokens):
        key = self._acquire()
        payload = {"model": modelo, "messages": [{"role": "user", "content": prompt}],
                   "temperature": 0.1, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        r = _session.post(URL, headers=headers, json=payload, timeout=REQ_TIMEOUT)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After", "")
            raise _Retryable("HTTP 429 rate limit", wait=float(ra) if ra.isdigit() else None)
        if r.status_code >= 500:
            raise _Retryable(f"HTTP {r.status_code} servidor")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


_pool_fast = _Pool(KEYS_FAST, MIN_INTERVAL)
_pool_think = _Pool(KEYS_THINK, THINK_INTERVAL) if KEYS_THINK else None


def tiene_think():
    """True si hay keys dedicadas (NVIDIA_API_KEY_5/_6) para el Nivel 2 thinking."""
    return _pool_think is not None


def _prompt(v):
    return (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\nEmpresa: {v['empresa']}\nUbicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\nDescripcion: {v['descripcion']}"
    )


def _evaluar(v, pool, modelos, max_tokens, etiqueta):
    """Evalua en un pool con lista de modelos (principal + fallback). Parseo defensivo del JSON.
    Devuelve {aceptar, motivo} o None si todo fallo."""
    prompt = _prompt(v)
    ultimo_error = ""
    for idx, modelo in enumerate(modelos):
        if idx > 0:
            print(f"# INFO fallback ({etiqueta}) -> {modelo}: '{v['titulo'][:30]}' ({ultimo_error[:40]})")
        backoff = 2.0
        for intento in range(2):
            try:
                content = pool.pedir(prompt, modelo, max_tokens)
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
    print(f"# WARN {etiqueta} '{v['titulo'][:40]}': {ultimo_error}")
    return None


def evaluar_vacante(v):
    """NIVEL 1: screening rapido con Maverick (fallback Llama 3.3). Nunca rompe el radar."""
    modelos = [MODEL] if MODEL == FALLBACK_MODEL else [MODEL, FALLBACK_MODEL]
    res = _evaluar(v, _pool_fast, modelos, MAX_TOKENS, "screening")
    return res if res else {"aceptar": False, "motivo": "error de evaluacion"}


def evaluar_profundo(v):
    """NIVEL 2: lectura profunda con thinking (Kimi -> DeepSeek) en el pool dedicado. Solo para
    los matches YA aceptados. Devuelve {aceptar, motivo} o None (si no hay pool think o falla)."""
    if not _pool_think:
        return None
    return _evaluar(v, _pool_think, [THINK_MODEL, THINK_FALLBACK], THINK_MAX_TOKENS, "profundo")
