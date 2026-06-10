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


# Cada fetcher = un "agente de busqueda". Se corren en paralelo desde radar.py
PORTALES = [fetch_remoteok, fetch_getonbrd]
