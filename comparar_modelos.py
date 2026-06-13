"""Eval de modelos por CALIDAD DE RAZONAMIENTO (no por velocidad).

Hector prioriza que el modelo RAZONE bien y analice cada vacante en detalle (el radar tiene 2h,
la velocidad no importa). Para medir eso objetivamente usamos un 'golden set': vacantes con el
veredicto CORRECTO conocido (segun criterios.txt). Cada modelo las evalua y se puntua cuantas
ACIERTA. Tambien medimos json_ok (confiabilidad de formato) y latencia (informativa, NO decide).
Guardamos los motivos para auditar la profundidad del razonamiento (sobre todo en los casos dificiles).

Resuelve los IDs exactos desde /v1/models (sin adivinar). Script de UN SOLO USO (no toca el radar).
"""
import os
import time
import json

import requests

KEY = os.environ["NVIDIA_API_KEY"]
BASE = "https://integrate.api.nvidia.com/v1"

with open("criterios.txt", encoding="utf-8") as f:
    CRITERIOS = f.read()

# Modelos a probar (palabra clave -> se resuelve el ID exacto del catalogo).
TARGETS = [
    "minimax-m3",        # NUEVO en NVIDIA - lo que queremos probar vs los thinking
    "kimi-k2.6",         # Nivel 2 actual (primario thinking)
    "deepseek-v4-pro",   # Nivel 2 actual (fallback thinking)
    "llama-4-maverick",  # referencia: el screener RAPIDO actual del radar
]

# Por si /v1/models falla o no matchea: IDs de respaldo (best-guess).
FALLBACK_IDS = {
    "glm-5.1": "zai/glm-5.1",
    "deepseek-v4-pro": "deepseek-ai/deepseek-v4-pro",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
    "deepseek-v4-flash": "deepseek-ai/deepseek-v4-flash",
    "nemotron-3-ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "minimax-m2.7": "minimaxai/minimax-m2.7",
    "minimax-m3": "minimaxai/minimax-m3",
    "mistral-medium-3.5": "mistralai/mistral-medium-3.5-128b",
    "llama-4-maverick": "meta/llama-4-maverick-17b-128e-instruct",
}

# GOLDEN SET: veredicto correcto conocido segun criterios.txt de Hector.
# 5 ACEPTAR + 5 DESCARTAR. Los casos [5] y [10] son DIFICILES (separan buen razonamiento):
#   [5] freelance de automatizacion en espanol -> SI encaja (su estrategia incluye freelance Workana).
#   [10] suena tecnico/espanol PERO exige ingles HABLADO + empresa vetada -> hay que DESCARTAR.
GOLDEN = [
    {"esperado": True,  "titulo": "Especialista en Automatizacion n8n (Remoto LATAM)", "empresa": "TechFlow", "ubicacion": "Remoto LATAM", "fuente": "Test",
     "descripcion": "Buscamos especialista en n8n para construir workflows e integraciones API y WhatsApp. 100% remoto, equipo en espanol, async. Salario 1000 EUR/mes. Abierto a Latinoamerica incluyendo Guatemala."},
    {"esperado": True,  "titulo": "AI Data Annotation Specialist (Spanish)", "empresa": "DataCorp", "ubicacion": "Remote Worldwide", "fuente": "Test",
     "descripcion": "Evaluate and rank LLM outputs in Spanish, annotate multimodal data. Fully remote, async, written English with tools is fine, NO calls. 15 USD/hr. Open worldwide."},
    {"esperado": True,  "titulo": "Soporte al Cliente Async en Espanol (chat/email)", "empresa": "HelpHero", "ubicacion": "Remoto", "fuente": "Test",
     "descripcion": "Atencion al cliente por chat y email en espanol. 100% remoto, async, SIN llamadas telefonicas. 600 USD/mes. LATAM bienvenido."},
    {"esperado": True,  "titulo": "AI Content QA / Prompt Engineer", "empresa": "PromptLab", "ubicacion": "Remote", "fuente": "Test",
     "descripcion": "Review AI-generated images, iterate and optimize prompts (Midjourney, Nano Banana). Remote, written English ok, NO voice calls. Project-based."},
    {"esperado": True,  "titulo": "Automatizacion de WhatsApp con Make.com (freelance)", "empresa": "PyME Cliente", "ubicacion": "Remoto", "fuente": "Test",
     "descripcion": "Proyecto FREELANCE: automatizar respuestas de WhatsApp con Make.com para una PyME. Remoto, en espanol, presupuesto USD 500, entrega por hitos."},
    {"esperado": False, "titulo": "Customer Success Manager (US clients)", "empresa": "SaaSCo", "ubicacion": "Remote", "fuente": "Test",
     "descripcion": "Remote role but requires DAILY VIDEO CALLS with US clients and fluent SPOKEN English. Manage accounts and present QBRs by voice."},
    {"esperado": False, "titulo": "Data Entry Clerk (US only)", "empresa": "DataAnnotation", "ubicacion": "United States", "fuente": "Test",
     "descripcion": "Remote data entry, but applicants must be US residents only. Company: DataAnnotation."},
    {"esperado": False, "titulo": "Senior Backend Engineer (Go/Kubernetes)", "empresa": "CloudScale", "ubicacion": "Remote", "fuente": "Test",
     "descripcion": "5+ years building distributed systems in Go, Kubernetes, microservices and high-scale infra. Remote."},
    {"esperado": False, "titulo": "Asistente Administrativo (hibrido CDMX)", "empresa": "OficinaMX", "ubicacion": "Ciudad de Mexico", "fuente": "Test",
     "descripcion": "Asistente administrativo, modalidad HIBRIDA: 3 dias presenciales en oficina en Ciudad de Mexico, 2 dias remotos."},
    {"esperado": False, "titulo": "Bilingual AI Trainer (Spanish data)", "empresa": "TELUS International", "ubicacion": "Remote", "fuente": "Test",
     "descripcion": "Work with Spanish-language data. NOTE: onboarding requires a 20-minute SPOKEN English video interview. Company: TELUS International."},
]


def resolver_ids():
    resolved = {}
    ids = []
    try:
        r = requests.get(f"{BASE}/models", headers={"Authorization": f"Bearer {KEY}"}, timeout=30)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    except Exception as e:
        print(f"# WARN no se pudo leer /v1/models ({e}); uso IDs de respaldo")
    for t in TARGETS:
        match = [i for i in ids if t in i.lower()]
        resolved[t] = match[0] if match else FALLBACK_IDS.get(t)
    return resolved, ids


def evaluar_con(modelo, v):
    prompt = (
        f"{CRITERIOS}\n\nVACANTE A EVALUAR:\n"
        f"Titulo: {v['titulo']}\nEmpresa: {v['empresa']}\nUbicacion: {v['ubicacion']}\n"
        f"Fuente: {v['fuente']}\nDescripcion: {v['descripcion']}"
    )
    payload = {"model": modelo, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_tokens": 500}
    t0 = time.monotonic()
    try:
        r = requests.post(f"{BASE}/chat/completions",
                          headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
                          json=payload, timeout=90)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return {"ok": False, "lat": dt, "err": f"HTTP{r.status_code}", "json_ok": False, "verdict": None, "motivo": ""}
        content = r.json()["choices"][0]["message"]["content"].strip()
        ini, fin = content.find("{"), content.rfind("}")
        verdict, motivo, json_ok = None, "", False
        if ini != -1 and fin != -1:
            try:
                res = json.loads(content[ini:fin + 1])
                json_ok = True
                verdict = bool(res.get("aceptar"))
                motivo = str(res.get("motivo", ""))[:150]
            except Exception:
                pass
        return {"ok": True, "lat": dt, "err": "", "json_ok": json_ok, "verdict": verdict, "motivo": motivo}
    except Exception as e:
        return {"ok": False, "lat": time.monotonic() - t0, "err": str(e)[:45], "json_ok": False, "verdict": None, "motivo": ""}


def main():
    resolved, ids = resolver_ids()
    print(f"# Catalogo NVIDIA: {len(ids)} modelos disponibles")
    _mm = [i for i in ids if "minimax" in i.lower()]
    print(f"# Modelos MiniMax en el catalogo: {_mm or 'NINGUNO'}")
    print("# IDs resueltos:")
    for t, mid in resolved.items():
        print(f"#   {t:20} -> {mid or 'NO ENCONTRADO'}")
    n_acc = sum(1 for g in GOLDEN if g["esperado"])
    print(f"# Golden set: {len(GOLDEN)} vacantes ({n_acc} ACEPTAR / {len(GOLDEN)-n_acc} DESCARTAR). Casos dificiles: [5] y [10].\n")

    tabla = {}
    for t in TARGETS:
        modelo = resolved[t]
        print(f"\n===== {t}  ({modelo}) =====")
        aciertos, jsons, lats, dificiles = 0, 0, [], ""
        for i, g in enumerate(GOLDEN):
            res = evaluar_con(modelo, g)
            time.sleep(2.5)  # ritmo bajo (~24 RPM) como el deep pass del radar: test de CALIDAD limpio, evita 429 falsos en los thinking
            lats.append(res["lat"])
            jsons += 1 if res["json_ok"] else 0
            correcto = res["ok"] and res["json_ok"] and (res["verdict"] == g["esperado"])
            aciertos += 1 if correcto else 0
            mark = "OK " if correcto else "XX "
            exp = "ACEPT" if g["esperado"] else "DESC "
            got = "ACEPT" if res["verdict"] else ("DESC " if res["verdict"] is False else "---- ")
            est = "" if res["ok"] else f"[{res['err']}]"
            if i in (4, 9):  # casos dificiles [5] y [10]
                dificiles += f"\n      DIFICIL[{i+1}] {mark} got={got} -> {res['motivo']}"
            print(f"  [{i+1:2}] esp={exp} got={got} {mark} {res['lat']:5.1f}s {est:9} | {g['titulo'][:32]:32} -> {res['motivo']}")
        n = len(GOLDEN)
        avg = sum(lats) / len(lats) if lats else 0
        tabla[t] = {"id": modelo, "aciertos": aciertos, "json": jsons, "lat": avg}
        print(f"  --- {t}: ACIERTOS {aciertos}/{n} | json_ok {jsons}/{n} | latencia prom {avg:.1f}s ---{dificiles}")

    print("\n\n========== RANKING POR ACIERTO (calidad de razonamiento) ==========")
    print(f"{'MODELO':20} {'ACIERTOS':9} {'json_ok':8} {'lat_prom':9} ID")
    for t in sorted(tabla, key=lambda x: (-tabla[x]["aciertos"], -tabla[x]["json"])):
        d = tabla[t]
        print(f"{t:20} {str(d['aciertos'])+'/'+str(len(GOLDEN)):9} {str(d['json'])+'/'+str(len(GOLDEN)):8} {d['lat']:6.1f}s   {d['id']}")
    print("===================================================================")


if __name__ == "__main__":
    main()
