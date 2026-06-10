"""Fetchers de portales de empleo (vias publicas, sin login).
Cada funcion devuelve una lista de vacantes normalizadas:
{id, titulo, empresa, ubicacion, descripcion, link, fuente}
"""
import re
import html
import requests
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar personal de Hector)"}
TIMEOUT = 30


def _get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"# WARN fetch {url}: {e}")
        return None


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
            "descripcion": (j.get("description", "") or "")[:1500],
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
                "descripcion": (attrs.get("description_headline", "") or attrs.get("description", "") or "")[:1500],
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
                "descripcion": (j.get("jobExcerpt", "") or j.get("jobDescription", "") or "")[:1500],
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
            "descripcion": (j.get("excerpt", "") or j.get("description", "") or "")[:1500],
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
                    "descripcion": (e.get("summary", "") or "")[:1500],
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
    for page in (1, 2, 3):
        try:
            r = requests.get(
                f"https://www.workana.com/jobs?language=es&page={page}",
                headers=hdrs, timeout=TIMEOUT,
            )
            r.raise_for_status()
            r.encoding = "utf-8"
            data = r.json()
        except Exception as e:
            print(f"# WARN fetch workana p{page}: {e}")
            continue
        lista = (((data or {}).get("results") or {}).get("results")) or []
        if not lista:
            break
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
                "descripcion": (desc + extra).strip()[:1500],
                "link": f"https://www.workana.com/job/{slug}",
                "fuente": "Workana",
            })
    return jobs


# Cada fetcher = un "agente de busqueda". Se corren en paralelo desde radar.py
PORTALES = [fetch_remoteok, fetch_getonbrd, fetch_jobicy, fetch_himalayas, fetch_weworkremotely,
            fetch_workana]
