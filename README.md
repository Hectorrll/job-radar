# 🛰️ Job Radar

Sistema **automatizado de búsqueda de empleo**. Cada 2 horas busca vacantes en varios
portales, las evalúa con IA según criterios personalizados, y envía los **matches por
Telegram**. Corre solo en la nube (GitHub Actions), **gratis, sin servidor propio**.

## ¿Cómo funciona?

```
[GitHub Actions · cron cada 2h]
   → busca vacantes en 3 portales EN PARALELO (RemoteOK, GetOnBrd, Jobicy)
   → filtra por palabras clave + descarta lo ya visto
   → evalúa cada nueva con IA (NVIDIA, gratis) contra criterios personalizados
   → envía los matches a Telegram (rol, empresa, link, por qué encaja)
   → guarda la memoria de lo ya avisado (seen.json)
```

## Stack

| Pieza | Rol |
|---|---|
| **GitHub Actions** | Reloj que dispara todo cada 2h (gratis, en la nube) |
| **Python** | Orquestador + fetchers + lógica |
| **NVIDIA NIM** (Llama 3.3 70B) | Cerebro que evalúa cada vacante — gratis |
| **Telegram Bot** | Canal de notificación de matches |

## Archivos

| Archivo | Qué hace |
|---|---|
| `radar.py` | Orquestador: busca → filtra → evalúa → notifica → guarda |
| `portales.py` | Un fetcher por portal (RemoteOK, GetOnBrd, Jobicy) |
| `evaluar.py` | Llama a la IA de NVIDIA para juzgar cada vacante |
| `notificar.py` | Envía mensajes a Telegram (con manejo de rate limit) |
| `criterios.txt` | Los criterios de filtrado (qué aceptar / descartar) |
| `seen.json` | Memoria de vacantes ya notificadas (evita repetir) |
| `.github/workflows/radar.yml` | El cron cada 2h + commit de la memoria |

## Configuración (secrets de GitHub)

En **Settings → Secrets and variables → Actions**:
- `NVIDIA_API_KEY` — API key gratis de build.nvidia.com
- `TELEGRAM_BOT_TOKEN` — token del bot (de @BotFather)
- `TELEGRAM_CHAT_ID` — chat donde llegan los avisos

## Mantenimiento

- **Correr a mano:** pestaña Actions → Job Radar → Run workflow.
- **Cambiar criterios:** editar `criterios.txt`.
- **Agregar un portal:** crear `fetch_xxx()` en `portales.py` (que devuelva la lista
  normalizada) y sumarlo a `PORTALES`.
- **Si un portal cambia y falla:** el radar no se rompe (cada fetcher está protegido);
  revisar el log del Action.

## Próximos pasos

- **Workana / LinkedIn / Upwork:** son apps de JavaScript (no se leen con un script
  simple) → requieren un navegador headless (**Obscura**) + cuenta secundaria. Fase 2.
- **Más portales del "Grupo A"** (con API pública) para más cobertura.

---

*Hecho por Hector Rodas · Orquestador de IA · Automatización con n8n / Python / IA.*
