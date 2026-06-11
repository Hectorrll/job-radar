"""DEMO (uso unico): como RAZONAN los modelos sobre las MISMAS vacantes reales.
Compara el screener (Maverick) vs los thinking (Kimi K2.6, DeepSeek V4 Pro), lado a lado,
mostrando veredicto + motivo COMPLETO de cada uno. Para que Hector vea la diferencia de
profundidad de razonamiento. Bajo volumen (15 llamadas) -> los thinking no dan 429.
"""
import os
import time
import json

import requests
import portales

KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()

MODELOS = [
    ("Maverick  (screener)", "meta/llama-4-maverick-17b-128e-instruct"),
    ("Kimi K2.6 (thinking)", "moonshotai/kimi-k2.6"),
    ("DeepSeek  (thinking)", "deepseek-ai/deepseek-v4-pro"),
]


def evaluar(modelo, v):
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\nEmpresa: {v['empresa']}\nUbicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\nDescripcion: {v['descripcion']}"
    )
    payload = {"model": modelo, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_tokens": 500}
    headers = {"Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    t0 = time.monotonic()
    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=90)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return f"[HTTP {r.status_code}] ({dt:.1f}s)"
        c = r.json()["choices"][0]["message"]["content"].strip()
        ini, fin = c.find("{"), c.rfind("}")
        if ini == -1 or fin == -1:
            return f"[sin JSON] ({dt:.1f}s)"
        res = json.loads(c[ini:fin + 1])
        verd = "ACEPTA  " if res.get("aceptar") else "descarta"
        return f"[{verd}] ({dt:.1f}s) {res.get('motivo', '')}"
    except Exception as e:
        return f"[ERROR: {str(e)[:45]}]"


def main():
    vac = portales.fetch_workana()[:5]
    print(f"# DEMO: {len(vac)} vacantes REALES de Workana, evaluadas por 3 modelos (screener vs thinking)")
    for i, v in enumerate(vac):
        print(f"\n{'=' * 75}")
        print(f"VACANTE [{i + 1}]: {v['titulo'][:68]}")
        print(f"   desc: {v['descripcion'][:170]}...")
        for nombre, mid in MODELOS:
            time.sleep(1.6)  # respetar rate
            print(f"   >> {nombre}: {evaluar(mid, v)}")


if __name__ == "__main__":
    main()
