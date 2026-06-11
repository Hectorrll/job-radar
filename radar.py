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
# RESCATE de falsos negativos (Nivel 2): cuantos rechazos DE NICHO re-lee el thinking para cazar
# matches que el screener (Maverick) tumbo por error (ej. confundir no-code/System.io con dev
# senior). Capado para no disparar el rate de los thinking. Solo aplica si hay keys think (5/6).
RESCATE_MAX = int(os.getenv("RADAR_RESCATE_MAX", "30"))

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
    # ingenieria/automatizacion junior + tooling (del CV 2026) - AGREGADO: solo amplia cobertura,
    # el evaluador (criterios.txt) sigue filtrando lo que no encaja (ej. dev senior).
    "python", "whatsapp", "chatbot", "scraping", "data pipeline", "rpa", "ai automation",
    "ai engineer", "google workspace", "github actions", "webhook", "openai",
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


# Nichos FUERTES de Hector (automatizacion/IA/data): para priorizar Y para el rescate de falsos
# negativos (donde el screener mas se equivoca, ej. confundir no-code con dev senior).
NICHO = ["n8n", "automation", "automatiz", "ai agent", "agente", "prompt", "workflow",
         "make.com", "zapier", "no-code", "low-code", "integration", "integraci",
         "annotation", "anotaci", "etiquet", "data label", "ai data", "ai content", "llm", "rlhf"]


def es_nicho(v):
    t = (v["titulo"] + " " + v["descripcion"]).lower()
    return any(k in t for k in NICHO)


def _mensaje(v, motivo):
    return (
        f"✅ <b>{html.escape(v['titulo'])}</b>\n"
        f"🏢 {html.escape(v['empresa'] or '—')}\n"
        f"📍 {html.escape(v['ubicacion'])}\n"
        f"🔎 {html.escape(v['fuente'])}\n"
        f"💡 {html.escape(motivo)}\n"
        f"🔗 {html.escape(v['link'])}"
    )


def main():
    seen = cargar_seen()
    _kf = len(evaluar.KEYS_FAST)
    print(f"# NIVEL 1 screening: {evaluar.MODEL} | {_kf} key(s) fast = ~{_kf*round(60/evaluar.MIN_INTERVAL)} RPM")
    if evaluar.tiene_think():
        print(f"# NIVEL 2 profundo: {evaluar.THINK_MODEL} (fallback {evaluar.THINK_FALLBACK}) | {len(evaluar.KEYS_THINK)} key(s) think dedicadas")
    else:
        print("# NIVEL 2 profundo: OFF (agregar NVIDIA_API_KEY_5/_6 para activarlo)")

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
    def _prioridad(v):
        return (0 if es_nicho(v) else 1, 0 if v["fuente"] == "GetOnBrd" else 1)

    nuevas.sort(key=_prioridad)  # primero las de tu nicho fuerte (automatizacion/IA), luego espanol
    print(f"# {len(nuevas)} nuevas relevantes (evaluare hasta {MAX_EVALUAR})")
    a_evaluar = nuevas[:MAX_EVALUAR]

    # 3) NIVEL 1: screening con Maverick EN PARALELO -> aceptados + rechazados.
    aceptadas, rechazadas = [], []
    if a_evaluar:
        with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as ex:
            veredictos = list(ex.map(evaluar.evaluar_vacante, a_evaluar))
        for v, ver in zip(a_evaluar, veredictos):
            estado = "ACEPTA" if ver["aceptar"] else "descarta"
            print(f"# [{estado}] {v['fuente']}: {v['titulo'][:45]} -> {ver['motivo'][:70]}")
            seen.add(v["id"])  # marcar como visto (se haya aceptado o no)
            (aceptadas if ver["aceptar"] else rechazadas).append((v, ver))

    # 4) NIVEL 2 (thinking, si hay keys 5/6): los modelos de RAZONAMIENTO son el ARBITRO FINAL,
    #    corrigiendo a Maverick en AMBAS direcciones:
    #    (a) re-leen los ACEPTADOS -> si CONFIRMAN, se manda (🧠); si DESCARTAN (detectan un
    #        dealbreaker que Maverick paso por alto: hibrido/presencial/otro pais/senior/ingles
    #        hablado), se FILTRA y NO se manda.
    #    (b) RESCATE: re-leen los rechazos DE NICHO -> si los ACEPTAN, los rescatan (🆘).
    #    El rescate (b) protege contra perder buenos; el filtro (a) saca la basura (hibridos, etc.).
    enviar = []   # lista de (v, motivo_final) a mandar a Telegram
    if not evaluar.tiene_think():
        enviar = [(v, ver["motivo"]) for v, ver in aceptadas]
    else:
        rescatables = [par for par in rechazadas if es_nicho(par[0])][:RESCATE_MAX]
        with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as ex:
            prof_acc = list(ex.map(lambda par: evaluar.evaluar_profundo(par[0]), aceptadas))
            prof_res = list(ex.map(lambda par: evaluar.evaluar_profundo(par[0]), rescatables))
        # (a) aceptados -> el thinking CONFIRMA (manda) o DESCARTA (filtra, no manda)
        n_filtrados = 0
        for (v, ver), prof in zip(aceptadas, prof_acc):
            if prof and prof.get("motivo"):
                decision = "ACEPTA" if prof["aceptar"] else "DESCARTA->filtra"
                print(f"#   [PROFUNDO] {v['fuente']}: {v['titulo'][:38]}")
                print(f"#       screening (Maverick): {ver['motivo'][:110]}")
                print(f"#       profundo  (thinking): [{decision}] {prof['motivo'][:110]}")
                if not prof["aceptar"]:
                    n_filtrados += 1   # dealbreaker detectado por el thinking -> NO se manda
                    continue
                motivo = "🧠 " + prof["motivo"]
            else:
                # Sin lectura profunda valida (fallo de IA) -> mandar con motivo de Maverick (no perder por un error tecnico).
                motivo = ver["motivo"]
            enviar.append((v, motivo))
        # (b) rescate de falsos negativos de nicho
        n_resc = 0
        for (v, ver), prof in zip(rescatables, prof_res):
            if prof and prof.get("aceptar"):   # el thinking RESCATA lo que Maverick tumbo mal
                n_resc += 1
                print(f"#   [RESCATE] {v['fuente']}: {v['titulo'][:38]}")
                print(f"#       Maverick descarto: {ver['motivo'][:95]}")
                print(f"#       thinking RESCATA:  {prof['motivo'][:95]}")
                enviar.append((v, "🧠🆘 RESCATADO (Maverick lo habia descartado): " + prof["motivo"]))
        print(f"# Nivel 2: {len(aceptadas)} aceptados | thinking FILTRO {n_filtrados} (dealbreakers) | rescato {n_resc}/{len(rescatables)}")

    # 5) NOTIFICAR a Telegram.
    if enviar:
        for v, motivo in enviar:
            notificar.enviar(_mensaje(v, motivo))
        print(f"# {len(enviar)} vacantes enviadas a Telegram")
    else:
        print(f"# 0 matches esta corrida (revise {len(a_evaluar)}) - sin aviso a Telegram (evita ruido)")

    # 6) GUARDAR vistos (el workflow lo commitea al repo).
    guardar_seen(seen)
    print("# listo")


if __name__ == "__main__":
    main()
