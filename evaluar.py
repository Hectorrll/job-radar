"""Evalua una vacante con un modelo de IA de NVIDIA (gratis, OpenAI-compatible).
Modelo: Qwen3.5 (el mejor del catalogo NVIDIA para espanol).
"""
import os
import json
import requests

NVIDIA_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "qwen/qwen3.5-122b-a10b"

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
        f"Descripcion: {v['descripcion'][:1200]}"
    )
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 250,
    }
    headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Accept": "application/json"}
    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=90)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        # Extrae el JSON aunque el modelo agregue texto/razonamiento alrededor.
        ini, fin = content.find("{"), content.rfind("}")
        if ini == -1 or fin == -1:
            return {"aceptar": False, "motivo": "respuesta sin JSON"}
        res = json.loads(content[ini:fin + 1])
        return {"aceptar": bool(res.get("aceptar")), "motivo": str(res.get("motivo", ""))[:200]}
    except Exception as e:
        print(f"# WARN evaluar '{v['titulo'][:40]}': {e}")
        return {"aceptar": False, "motivo": f"error: {e}"}
