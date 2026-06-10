"""Evalua una vacante con un modelo de IA de NVIDIA (gratis, OpenAI-compatible).
Modelo: Llama 3.3 70B (rapido, sin "thinking", buen espanol).
Reintenta 1 vez si NVIDIA esta lento/saturado (free tier).
"""
import os
import json
import requests

NVIDIA_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.3-70b-instruct"

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()


def evaluar_vacante(v):
    """Devuelve {'aceptar': bool, 'motivo': str}. Nunca rompe el radar."""
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\n"
        f"Empresa: {v['empresa']}\n"
        f"Ubicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\n"
        f"Descripcion: {v['descripcion'][:900]}"
    )
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 120,
    }
    headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Accept": "application/json"}
    ultimo_error = ""
    for intento in range(2):  # 1 reintento si falla (NVIDIA free tier lento)
        try:
            r = requests.post(URL, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            ini, fin = content.find("{"), content.rfind("}")
            if ini == -1 or fin == -1:
                return {"aceptar": False, "motivo": "respuesta sin JSON"}
            res = json.loads(content[ini:fin + 1])
            return {"aceptar": bool(res.get("aceptar")), "motivo": str(res.get("motivo", ""))[:200]}
        except Exception as e:
            ultimo_error = str(e)
    print(f"# WARN evaluar '{v['titulo'][:40]}': {ultimo_error}")
    return {"aceptar": False, "motivo": f"error: {ultimo_error}"}
