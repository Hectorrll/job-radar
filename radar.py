"""Job Radar 24/7 - orquestador.
Flujo: buscar (portales en paralelo) -> prefiltrar -> dedup -> evaluar (en paralelo
con IA) -> notificar a Telegram -> guardar vistos.
"""
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor

import portales
import evaluar
import notificar

SEEN_FILE = pathlib.Path("seen.json")
MAX_EVALUAR = 15          # cuantas vacantes nuevas evaluar por corrida (controla volumen)

# Pre-filtro barato por palabras clave: descarta lo obviamente irrelevante ANTES
# de gastar llamadas de IA. Solo lo que pase esto se evalua con Qwen3.5.
KEYWORDS = [
    "n8n", "make.com", "zapier", "automation", "automatizaci", "workflow",
    "integration", "integraci", "no-code", "low-code", "ai agent", "agente",
    "prompt", "content qa", "quality", "annotation", "anotaci", "data entry",
    "soporte", "support", "spanish", "espanol", "español", "bilingual",
    "bilingüe", "customer", "virtual assistant", "asistente",
]


def cargar_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def guardar_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1), encoding="utf-8")


def es_relevante(v):
    texto = (v["titulo"] + " " + v["descripcion"]).lower()
    return any(k in texto for k in KEYWORDS)


def main():
    seen = cargar_seen()

    # 1) BUSCAR: cada portal es un "agente" que corre EN PARALELO.
    with ThreadPoolExecutor(max_workers=max(1, len(portales.PORTALES))) as ex:
        resultados = list(ex.map(lambda f: f(), portales.PORTALES))
    todas = [v for lista in resultados for v in lista]
    print(f"# {len(todas)} vacantes traidas de {len(portales.PORTALES)} portales")

    # 2) PRE-FILTRAR por keywords + DEDUP contra lo ya visto.
    nuevas = [v for v in todas if es_relevante(v) and v["id"] not in seen]
    nuevas.sort(key=lambda v: 0 if v["fuente"] == "GetOnBrd" else 1)  # espanol/Latam primero
    print(f"# {len(nuevas)} nuevas relevantes (evaluare hasta {MAX_EVALUAR})")
    a_evaluar = nuevas[:MAX_EVALUAR]

    # 3) EVALUAR con IA EN PARALELO (varios "agentes evaluadores", 1 sola API key).
    aceptadas = []
    if a_evaluar:
        with ThreadPoolExecutor(max_workers=3) as ex:
            veredictos = list(ex.map(evaluar.evaluar_vacante, a_evaluar))
        for v, ver in zip(a_evaluar, veredictos):
            estado = "ACEPTA" if ver["aceptar"] else "descarta"
            print(f"# [{estado}] {v['fuente']}: {v['titulo'][:45]} -> {ver['motivo'][:70]}")
            seen.add(v["id"])  # marcar como visto (se haya aceptado o no)
            if ver["aceptar"]:
                aceptadas.append((v, ver))

    # 4) NOTIFICAR a Telegram.
    if aceptadas:
        for v, ver in aceptadas:
            msg = (
                f"✅ <b>{v['titulo']}</b>\n"
                f"🏢 {v['empresa'] or '—'}\n"
                f"📍 {v['ubicacion']}\n"
                f"🔎 {v['fuente']}\n"
                f"💡 {ver['motivo']}\n"
                f"🔗 {v['link']}"
            )
            notificar.enviar(msg)
        print(f"# {len(aceptadas)} vacantes enviadas a Telegram")
    else:
        notificar.enviar(f"🛰️ Radar: 0 vacantes nuevas que encajen (revise {len(a_evaluar)} candidatas).")

    # 5) GUARDAR vistos (el workflow lo commitea al repo).
    guardar_seen(seen)
    print("# listo")


if __name__ == "__main__":
    main()
