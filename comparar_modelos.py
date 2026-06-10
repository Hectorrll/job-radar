"""Auditoria cabeza-a-cabeza de modelos NVIDIA NIM para el radar.

Evalua las MISMAS vacantes con varios modelos y mide, por cada llamada:
  - latencia (segundos)
  - si responde (HTTP 200 / 404 / timeout / error)
  - si devuelve JSON limpio parseable ({aceptar, motivo})
  - el veredicto (acepta/descarta) y el motivo

Asi se compara DeepSeek V4 Pro vs los Llama con DATOS, no con benchmarks.
Es un script de UN SOLO USO (no toca el radar). Se corre con el workflow comparar.yml.
"""
import os
import time
import json

import requests
import portales

MODELOS = [
    "deepseek-ai/deepseek-v4-pro",            # chino, razonador/agentico (lo que pidio Hector)
    "meta/llama-4-maverick-17b-128e-instruct",  # principal actual del radar
    "meta/llama-3.3-70b-instruct",            # fallback probado
]

KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()


def evaluar_con(modelo, v):
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\nEmpresa: {v['empresa']}\nUbicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\nDescripcion: {v['descripcion']}"
    )
    payload = {"model": modelo, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_tokens": 200}
    headers = {"Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    t0 = time.monotonic()
    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=90)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return {"ok": False, "lat": dt, "err": f"HTTP {r.status_code}",
                    "json_ok": False, "verdict": None, "motivo": "", "raw_len": 0}
        content = r.json()["choices"][0]["message"]["content"].strip()
        ini, fin = content.find("{"), content.rfind("}")
        json_ok, verdict, motivo = False, None, ""
        if ini != -1 and fin != -1:
            try:
                res = json.loads(content[ini:fin + 1])
                json_ok = True
                verdict = bool(res.get("aceptar"))
                motivo = str(res.get("motivo", ""))[:90]
            except Exception:
                json_ok = False
        return {"ok": True, "lat": dt, "err": "", "json_ok": json_ok,
                "verdict": verdict, "motivo": motivo, "raw_len": len(content)}
    except Exception as e:
        return {"ok": False, "lat": time.monotonic() - t0, "err": str(e)[:55],
                "json_ok": False, "verdict": None, "motivo": "", "raw_len": 0}


def main():
    vac = portales.fetch_workana()[:6]   # muestra fija: 6 vacantes reales (espanol, variadas)
    print(f"# Muestra: {len(vac)} vacantes de Workana")
    for i, v in enumerate(vac):
        print(f"#   [{i+1}] {v['titulo'][:60]}")

    resumen = {}
    for modelo in MODELOS:
        print(f"\n===== MODELO: {modelo} =====")
        lats, oks, jsons, accs = [], 0, 0, 0
        for i, v in enumerate(vac):
            res = evaluar_con(modelo, v)
            time.sleep(1.6)  # respetar el limite de 40 RPM (1 llamada cada 1.6s)
            lats.append(res["lat"])
            oks += 1 if res["ok"] else 0
            jsons += 1 if res["json_ok"] else 0
            accs += 1 if res["verdict"] else 0
            estado = "OK  " if res["ok"] else f"FAIL[{res['err']}]"
            jflag = "json_ok " if res["json_ok"] else "json_NO "
            vflag = "ACEPTA  " if res["verdict"] else ("descarta" if res["verdict"] is False else "  --    ")
            print(f"  [{i+1}] {res['lat']:5.1f}s {estado} {jflag}{vflag} raw={res['raw_len']:4d} | "
                  f"{v['titulo'][:30]:30} -> {res['motivo']}")
        n = len(vac)
        avg = sum(lats) / len(lats) if lats else 0
        resumen[modelo] = {"responde": f"{oks}/{n}", "json_ok": f"{jsons}/{n}",
                           "acepta": f"{accs}/{n}", "lat_prom": f"{avg:.1f}s"}
        print(f"  --- {modelo}: responde {oks}/{n} | json_ok {jsons}/{n} | acepta {accs}/{n} | latencia prom {avg:.1f}s ---")

    print("\n\n================ RESUMEN COMPARATIVO ================")
    print(f"{'MODELO':45} {'responde':9} {'json_ok':8} {'acepta':7} {'lat_prom':8}")
    for modelo, r in resumen.items():
        print(f"{modelo:45} {r['responde']:9} {r['json_ok']:8} {r['acepta']:7} {r['lat_prom']:8}")
    print("====================================================")


if __name__ == "__main__":
    main()
