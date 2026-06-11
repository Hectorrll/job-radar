"""Job Radar 24/7 - orquestador.
Flujo: buscar (portales en paralelo) -> prefiltrar -> dedup -> evaluar (en paralelo
con IA) -> notificar a Telegram -> guardar vistos.
"""
import os
import json
import html
import pathlib
from concurrent.futures import ThreadPoolExecutor

import portales
import evaluar
import notificar

SEEN_FILE = pathlib.Path("seen.json")
# Cuantas vacantes NUEVAS evaluar por corrida. 400 aprovecha el TRIPLE presupuesto de 3 keys
# NVIDIA (~114 RPM). Tras el dedup casi nunca hay tantas nuevas; el tope solo aplica en corridas
# frias/grandes. Seguro: evaluar.py limita el ritmo POR KEY por debajo de 40 RPM (no rompe NVIDIA).
MAX_EVALUAR = int(os.getenv("RADAR_MAX_EVALUAR", "400"))
# Hilos de evaluacion en paralelo. El limitador de ritmo (evaluar.py) es el guard real del
# rate; estos hilos solo mantienen lleno el pipeline para exprimir la API al maximo (~40 RPM).
EVAL_WORKERS = int(os.getenv("RADAR_EVAL_WORKERS", "8"))

# Pre-filtro barato por palabras clave: descarta lo obviamente irrelevante ANTES
# de gastar llamadas de IA. Solo lo que pase esto se evalua con Qwen3.5.
KEYWORDS = [
    # automatizacion / IA (nicho fuerte)
    "n8n", "make.com", "zapier", "automation", "automatizaci", "workflow",
    "integration", "integraci", "no-code", "low-code", "ai agent", "agente",
    "prompt", "ai content", "ai data", "machine learning", "llm", "rlhf",
    # QA / anotacion / etiquetado (diferenciador de Hector)
    "content qa", "quality", "annotation", "anotaci", "labeling", "etiquet",
    # data / oficina
    "data entry", "data label", "transcrip", "spreadsheet", "hoja de calcul", "crm", "hubspot",
    # soporte async / operaciones
    "soporte", "support", "customer", "virtual assistant", "asistente",
    "operacion", "back office", "backoffice", "lifecycle", "data entry",
    # redaccion / traduccion (ingles ESCRITO ok)
    "traduc", "translat", "redacci", "redactor", "copywrit",
    # idioma
    "spanish", "espanol", "español", "bilingual", "bilingüe",
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
    print(f"# modelo IA: {evaluar.MODEL} (fallback: {evaluar.FALLBACK_MODEL}) | {len(evaluar.KEYS)} key(s) x ~{round(60/evaluar.MIN_INTERVAL)} RPM = ~{len(evaluar.KEYS)*round(60/evaluar.MIN_INTERVAL)} RPM total")

    # 1) BUSCAR: cada portal es un "agente" que corre EN PARALELO.
    with ThreadPoolExecutor(max_workers=max(1, len(portales.PORTALES))) as ex:
        resultados = list(ex.map(lambda f: f(), portales.PORTALES))
    todas = [v for lista in resultados for v in lista]
    # Desglose POR PORTAL (transparencia: confirmar que TODOS traen, detectar si alguno da 0)
    for f, lista in zip(portales.PORTALES, resultados):
        nombre = lista[0]["fuente"] if lista else f.__name__.replace("fetch_", "")
        print(f"#   - {nombre}: {len(lista)}")
    print(f"# {len(todas)} vacantes traidas de {len(portales.PORTALES)} portales")

    # 2) PRE-FILTRAR por keywords + DEDUP contra lo ya visto.
    nuevas = [v for v in todas if es_relevante(v) and v["id"] not in seen]
    # dedup cross-portal DENTRO de la corrida: mismo trabajo en 2 boards = 1 solo aviso
    _k, _dedup = set(), []
    for v in nuevas:
        clave = (v["titulo"].lower().strip() + "|" + v["empresa"].lower().strip())
        if clave not in _k:
            _k.add(clave)
            _dedup.append(v)
    nuevas = _dedup
    nicho = ["n8n", "automation", "automatiz", "ai agent", "agente", "prompt",
             "workflow", "make.com", "zapier", "no-code", "low-code"]

    def _prioridad(v):
        t = (v["titulo"] + " " + v["descripcion"]).lower()
        return (0 if any(k in t for k in nicho) else 1, 0 if v["fuente"] == "GetOnBrd" else 1)

    nuevas.sort(key=_prioridad)  # primero las de tu nicho fuerte (automatizacion/IA), luego espanol
    print(f"# {len(nuevas)} nuevas relevantes (evaluare hasta {MAX_EVALUAR})")
    a_evaluar = nuevas[:MAX_EVALUAR]

    # 3) EVALUAR con IA EN PARALELO (varios "agentes evaluadores", 1 sola API key).
    aceptadas = []
    if a_evaluar:
        with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as ex:
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
                f"✅ <b>{html.escape(v['titulo'])}</b>\n"
                f"🏢 {html.escape(v['empresa'] or '—')}\n"
                f"📍 {html.escape(v['ubicacion'])}\n"
                f"🔎 {html.escape(v['fuente'])}\n"
                f"💡 {html.escape(ver['motivo'])}\n"
                f"🔗 {html.escape(v['link'])}"
            )
            notificar.enviar(msg)
        print(f"# {len(aceptadas)} vacantes enviadas a Telegram")
    else:
        print(f"# 0 matches esta corrida (revise {len(a_evaluar)}) - sin aviso a Telegram (evita ruido)")

    # 5) GUARDAR vistos (el workflow lo commitea al repo).
    guardar_seen(seen)
    print("# listo")


if __name__ == "__main__":
    main()
