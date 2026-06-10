"""Fetchers de portales de empleo (vias publicas, sin login).
Cada funcion devuelve una lista de vacantes normalizadas:
{id, titulo, empresa, ubicacion, descripcion, link, fuente}
"""
import requests

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
            continue  # salta el aviso legal / elementos raros
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
    """Get on Board: fuerte en Latam/español. Formato JSON:API."""
    url = "https://www.getonbrd.com/api/v0/search/jobs?query=&per_page=80&expand=[company]"
    data = _get_json(url)
    if not isinstance(data, dict) or "data" not in data:
        return []
    jobs = []
    for j in data.get("data", []):
        attrs = j.get("attributes", {}) or {}
        empresa = ""
        comp = (j.get("relationships", {}) or {}).get("company", {})
        if isinstance(comp, dict):
            empresa = ((comp.get("data", {}) or {}).get("attributes", {}) or {}).get("name", "")
        paises = attrs.get("countries", []) or []
        modalidad = attrs.get("remote_modality", "") or ""
        jobs.append({
            "id": f"getonbrd-{j.get('id')}",
            "titulo": attrs.get("title", "") or "",
            "empresa": empresa or "",
            "ubicacion": f"{modalidad} {', '.join(paises)}".strip() or "Remoto",
            "descripcion": (attrs.get("description_headline", "") or attrs.get("description", "") or "")[:1500],
            "link": (j.get("links", {}) or {}).get("public_url", "") or "",
            "fuente": "GetOnBrd",
        })
    return jobs


# Cada fetcher = un "agente de busqueda". Se corren en paralelo desde radar.py
PORTALES = [fetch_remoteok, fetch_getonbrd]
