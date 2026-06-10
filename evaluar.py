"""Evalua una vacante con un modelo de IA de NVIDIA (gratis, OpenAI-compatible).
Modelo principal: Qwen3.5-122B (MoE, mejor espanol del catalogo, rapido, no-"thinking").
Si el principal falla o NVIDIA lo deprecia, cae a un FALLBACK probado (Llama 3.3 70B).
El ID se puede sobreescribir sin tocar codigo con la env var RADAR_MODEL.
Reintenta si NVIDIA esta lento/saturado (free tier).
"""
import os
import json
import requests

NVIDIA_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Principal (mejor espanol) + fallback probado. RADAR_MODEL permite cambiar sin editar codigo.
MODEL = os.getenv("RADAR_MODEL", "qwen/qwen3.5-122b-a10b")
FALLBACK_MODEL = "meta/llama-3.3-70b-instruct"

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()


def _pedir(prompt, modelo):
    """Una llamada al modelo. Devuelve el texto de la respuesta o lanza excepcion."""
    payload = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 120,
    }
    headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Accept": "application/json"}
    r = requests.post(URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def evaluar_vacante(v):
    """Devuelve {'aceptar': bool, 'motivo': str}. Nunca rompe el radar.
    Prueba MODEL; si la llamada falla (error/timeout/ID invalido), cae a FALLBACK_MODEL."""
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\n"
        f"Empresa: {v['empresa']}\n"
        f"Ubicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\n"
        f"Descripcion: {v['descripcion'][:900]}"
    )
    modelos = [MODEL] if MODEL == FALLBACK_MODEL else [MODEL, FALLBACK_MODEL]
    ultimo_error = ""
    for modelo in modelos:
        for intento in range(2):  # 1 reintento por modelo (NVIDIA free tier lento)
            try:
                content = _pedir(prompt, modelo)
                ini, fin = content.find("{"), content.rfind("}")
                if ini == -1 or fin == -1:
                    return {"aceptar": False, "motivo": "respuesta sin JSON"}
                res = json.loads(content[ini:fin + 1])
                return {"aceptar": bool(res.get("aceptar")), "motivo": str(res.get("motivo", ""))[:200]}
            except Exception as e:
                ultimo_error = str(e)
    print(f"# WARN evaluar '{v['titulo'][:40]}': {ultimo_error}")
    return {"aceptar": False, "motivo": f"error: {ultimo_error}"}
