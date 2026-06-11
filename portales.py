"""Fetchers de portales de empleo (vias publicas, sin login).
Cada funcion devuelve una lista de vacantes normalizadas:
{id, titulo, empresa, ubicacion, descripcion, link, fuente}
"""
import re
import html
import time
import requests
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar personal de Hector)"}
TIMEOUT = 30
MAX_DESC = 2500   # cuanto texto guardamos de cada vacante (para evaluar con mas detalle)
_session = requests.Session()   # reusa conexiones TCP = fetch mas rapido


def _get_json(url):
    try:
        r = _session.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"# WARN fetch {url}: {e}")
        return None


def _get_text(url):
    """Como _get_json pero devuelve texto/HTML (para portales que no dan JSON)."""
    try:
        r = _session.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"# WARN fetch {url}: {e}")
        return None


def _entre(s, a, b):
    """Extrae el texto entre el marcador 'a' y el 'b'. '' si no esta."""
    i = s.find(a)
    if i == -1:
        return ""
    i += len(a)
    j = s.find(b, i)
    return s[i:j] if j != -1 else ""


def _limpiar(s):
    """Quita tags HTML y desescapa entidades."""
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch_remoteok():
    """RemoteOK: remoto global, mayormente tech. El 1er elemento es aviso legal."""
    data = _get_json("https://remoteok.com/api")
    if not isinstance(data, list):
        return []
    jobs = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j or "id" not in j:
            continue
        jobs.append({
            "id": f"remoteok-{j.get('id')}",
            "titulo": j.get("position", "") or "",
            "empresa": j.get("company", "") or "",
            "ubicacion": j.get("location", "") or "Remoto",
            "descripcion": (j.get("description", "") or "")[:MAX_DESC],
            "link": j.get("url") or j.get("apply_url", "") or "",
            "fuente": "RemoteOK",
        })
    return jobs


def fetch_getonbrd():
    """Get on Board: Latam/espanol. Se busca por los nichos de Hector (sin expand,
    que causaba error 500). Junta y deduplica los resultados de varias busquedas."""
    queries = ["automatizacion", "n8n", "soporte", "data", "asistente", "ai"]
    jobs, vistos = [], set()
    for q in queries:
        data = _get_json(f"https://www.getonbrd.com/api/v0/search/jobs?query={q}&per_page=30")
        if not isinstance(data, dict) or "data" not in data:
            continue
        for j in data.get("data", []):
            jid = j.get("id")
            if not jid or jid in vistos:
                continue
            vistos.add(jid)
            attrs = j.get("attributes", {}) or {}
            jobs.append({
                "id": f"getonbrd-{jid}",
                "titulo": attrs.get("title", "") or "",
                "empresa": "",
                "ubicacion": attrs.get("remote_modality", "") or "Remoto",
                "descripcion": (attrs.get("description_headline", "") or attrs.get("description", "") or "")[:MAX_DESC],
                "link": (j.get("links", {}) or {}).get("public_url", "") or "",
                "fuente": "GetOnBrd",
            })
    return jobs


def fetch_jobicy():
    """Jobicy: remoto global. Busca en categorias afines a los nichos de Hector."""
    jobs, vistos = [], set()
    for tag in ["support", "supporting", "data-science", "dev", "copywriting", "admin"]:
        data = _get_json(f"https://jobicy.com/api/v2/remote-jobs?count=40&tag={tag}")
        if not isinstance(data, dict):
            continue
        lista = data.get("jobs") or data.get("data") or []
        for j in lista:
            jid = j.get("id")
            if not jid or jid in vistos:
                continue
            vistos.add(jid)
            jobs.append({
                "id": f"jobicy-{jid}",
                "titulo": j.get("jobTitle", "") or "",
                "empresa": j.get("companyName", "") or "",
                "ubicacion": j.get("jobGeo", "") or "Remoto",
                "descripcion": (j.get("jobExcerpt", "") or j.get("jobDescription", "") or "")[:MAX_DESC],
                "link": j.get("url", "") or "",
                "fuente": "Jobicy",
            })
    return jobs


def fetch_himalayas():
    """Himalayas: ~100k trabajos remotos globales. Trae los paises permitidos."""
    data = _get_json("https://himalayas.app/jobs/api?limit=100")
    if not isinstance(data, dict):
        return []
    jobs = []
    for j in (data.get("jobs") or []):
        restr = j.get("locationRestrictions") or []
        ubic = ", ".join(restr) if restr else "Mundial"
        clave = j.get("guid") or j.get("id") or j.get("applicationLink", "")
        jobs.append({
            "id": f"himalayas-{clave}",
            "titulo": j.get("title", "") or "",
            "empresa": j.get("companyName", "") or "",
            "ubicacion": ubic,
            "descripcion": (j.get("excerpt", "") or j.get("description", "") or "")[:MAX_DESC],
            "link": j.get("applicationLink", "") or "",
            "fuente": "Himalayas",
        })
    return jobs


def fetch_weworkremotely():
    """WeWorkRemotely: gran board remoto, via RSS por categoria."""
    feeds = [
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
    ]
    jobs = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                jobs.append({
                    "id": f"wwr-{e.get('id', e.get('link', ''))}",
                    "titulo": e.get("title", "") or "",
                    "empresa": "",
                    "ubicacion": "Remoto",
                    "descripcion": (e.get("summary", "") or "")[:MAX_DESC],
                    "link": e.get("link", "") or "",
                    "fuente": "WeWorkRemotely",
                })
        except Exception as ex:
            print(f"# WARN wwr {url}: {ex}")
    return jobs


def fetch_workana():
    """Workana: freelance LATAM/espanol. La web es una SPA (AngularJS), pero su
    endpoint interno devuelve JSON sin login si se pide como XHR. Trae varias
    paginas del feed en espanol. Nunca rompe: ante cualquier fallo devuelve []."""
    hdrs = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    jobs, vistos = [], set()
    for page in range(1, 6):   # hasta 5 paginas: mas cobertura de su nicho ES/LATAM
        try:
            r = _session.get(
                f"https://www.workana.com/jobs?language=es&page={page}",
                headers=hdrs, timeout=TIMEOUT,
            )
            r.raise_for_status()
            r.encoding = "utf-8"
            data = r.json()
        except Exception as e:
            print(f"# WARN fetch workana p{page}: {e}")
            break
        lista = (((data or {}).get("results") or {}).get("results")) or []
        antes = len(vistos)
        for j in lista:
            slug = j.get("slug") or ""
            if not slug or slug in vistos:
                continue
            vistos.add(slug)
            traw = j.get("title", "") or ""
            m = re.search(r'<span[^>]*title="([^"]+)"', traw)
            titulo = html.unescape(m.group(1)) if m else re.sub(r"<[^>]+>", "", traw).strip()
            cm = re.search(r"country=([A-Z]{2})", j.get("country", "") or "")
            ubic = cm.group(1) if cm else "Remoto"
            skills = ", ".join(
                s.get("anchorText", "") for s in (j.get("skills") or []) if s.get("anchorText")
            )
            desc = j.get("description", "") or ""
            extra = (f" | Skills: {skills}" if skills else "")
            extra += (f" | Presupuesto: {j.get('budget','')}" if j.get("budget") else "")
            jobs.append({
                "id": f"workana-{slug}",
                "titulo": titulo,
                "empresa": j.get("authorName", "") or "",
                "ubicacion": ubic,
                "descripcion": (desc + extra).strip()[:MAX_DESC],
                "link": f"https://www.workana.com/job/{slug}",
                "fuente": "Workana",
            })
        if len(vistos) == antes:   # pagina sin vacantes nuevas (fin de resultados) -> corto
            break
        time.sleep(0.4)            # ritmo educado entre paginas
    return jobs


def fetch_linkedin():
    """LinkedIn via el endpoint GUEST publico (sin login, sin riesgo de ban). Devuelve HTML
    de tarjetas; se parsea con regex. El link se arma desde el jobPosting id (robusto).
    Guest no da descripcion larga -> descripcion = titulo. Filtro remoto (f_WT=2)."""
    base = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            "?keywords={kw}&location=Latin%20America&f_WT=2&start=0")
    queries = ["n8n", "automation", "ai%20annotation", "data%20entry",
               "prompt%20engineer", "soporte%20bilingue", "ai%20content"]
    jobs, vistos = [], set()
    for kw in queries:
        t = _get_text(base.format(kw=kw))
        if not t:
            continue
        for c in re.split(r"<li>", t):
            m = re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', c)
            if not m:
                continue
            jid = m.group(1)
            if jid in vistos:
                continue
            vistos.add(jid)
            titulo = _limpiar(_entre(c, 'base-search-card__title">', "</h3>"))
            if not titulo:
                continue
            jobs.append({
                "id": f"linkedin-{jid}",
                "titulo": titulo,
                "empresa": _limpiar(_entre(c, 'base-search-card__subtitle">', "</h4>")),
                "ubicacion": _limpiar(_entre(c, 'job-search-card__location">', "</span>")) or "Remoto",
                "descripcion": titulo[:MAX_DESC],  # guest no da el cuerpo
                "link": f"https://www.linkedin.com/jobs/view/{jid}",
                "fuente": "LinkedIn",
            })
    return jobs


def fetch_remotive():
    """Remotive: agregador remoto global, API JSON gratis."""
    data = _get_json("https://remotive.com/api/remote-jobs?limit=100")
    if not isinstance(data, dict):
        return []
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "id": f"remotive-{j.get('id')}",
            "titulo": j.get("title", "") or "",
            "empresa": j.get("company_name", "") or "",
            "ubicacion": j.get("candidate_required_location", "") or "Remoto",
            "descripcion": _limpiar(j.get("description", ""))[:MAX_DESC],
            "link": j.get("url", "") or "",
            "fuente": "Remotive",
        })
    return jobs


def fetch_arbeitnow():
    """Arbeitnow: board global, API JSON gratis (mucho EU/tech; el prefiltro filtra)."""
    data = _get_json("https://www.arbeitnow.com/api/job-board-api")
    if not isinstance(data, dict):
        return []
    jobs = []
    for j in data.get("data", []):
        loc = j.get("location")
        ubic = ", ".join(loc) if isinstance(loc, list) else (loc or "Remoto")
        jobs.append({
            "id": f"arbeitnow-{j.get('slug')}",
            "titulo": j.get("title", "") or "",
            "empresa": j.get("company_name", "") or "",
            "ubicacion": ubic or "Remoto",
            "descripcion": _limpiar(j.get("description", ""))[:MAX_DESC],
            "link": j.get("url", "") or "",
            "fuente": "Arbeitnow",
        })
    return jobs


def fetch_workingnomads():
    """Working Nomads: jobs remotos globales, API JSON gratis."""
    data = _get_json("https://www.workingnomads.com/api/exposed_jobs/")
    if not isinstance(data, list):
        return []
    jobs = []
    for j in data:
        url = j.get("url", "") or ""
        slug = url.rstrip("/").split("/")[-1] or (j.get("title", "") or "")
        jobs.append({
            "id": f"workingnomads-{slug}",
            "titulo": j.get("title", "") or "",
            "empresa": j.get("company_name", "") or "",
            "ubicacion": j.get("location", "") or "Remoto",
            "descripcion": _limpiar(j.get("description", ""))[:MAX_DESC],
            "link": url,
            "fuente": "Working Nomads",
        })
    return jobs


def fetch_n8n_community():
    """n8n Community Jobs (Discourse JSON). NICHO EXACTO de Hector: gigs de n8n/automatizacion/IA.
    Salta los posts fijados (pinned, ej. 'About the category'). El body no viene en el listado."""
    data = _get_json("https://community.n8n.io/c/jobs/13.json")
    if not isinstance(data, dict):
        return []
    jobs = []
    for t in ((data.get("topic_list", {}) or {}).get("topics", []) or []):
        if t.get("pinned") or not t.get("id"):
            continue
        titulo = t.get("title", "") or ""
        if not titulo:
            continue
        jobs.append({
            "id": f"n8n-{t.get('id')}",
            "titulo": titulo,
            "empresa": "",
            "ubicacion": "Remoto",
            "descripcion": titulo[:MAX_DESC],  # el listado no trae el cuerpo
            "link": f"https://community.n8n.io/t/{t.get('slug', '')}/{t.get('id')}",
            "fuente": "n8n Community",
        })
    return jobs


# Cada fetcher = un "agente de busqueda". Se corren en paralelo desde radar.py
PORTALES = [fetch_remoteok, fetch_getonbrd, fetch_jobicy, fetch_himalayas, fetch_weworkremotely,
            fetch_workana, fetch_linkedin, fetch_remotive, fetch_arbeitnow,
            fetch_workingnomads, fetch_n8n_community]
