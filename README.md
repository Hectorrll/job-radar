# 🛰️ Job Radar — Buscador de empleo autónomo con IA

> Sistema **24/7 sin servidor** que busca vacantes de empleo remoto en **12 portales**, las evalúa
> con un **pipeline de IA de dos niveles** (screening rápido + lectura profunda con modelos de
> razonamiento) según un perfil configurable, y envía solo los **matches reales a Telegram**.
> Corre solo en la nube (GitHub Actions + cron externo), con **costo de infraestructura $0**.

**Stack:** Python · GitHub Actions · NVIDIA NIM (LLMs) · Telegram Bot API · cron-job.org
**Estado:** en producción · ~**1.200 vacantes analizadas por corrida** · una corrida por hora

> 🇬🇧 **TL;DR (EN):** A serverless, fully automated job-search agent. Every run it pulls ~1,200
> remote postings from 12 sources, runs them through a **two-tier LLM pipeline** (a fast screener
> over the full volume + a reasoning model that deep-reviews finalists and *rescues* false
> negatives), and pushes only real matches to Telegram. $0 infra, runs on GitHub Actions.

---

## 🎯 El problema

Buscar empleo remoto a mano es repetitivo y se pierden oportunidades: hay que revisar decenas de
portales todos los días, leer descripciones largas, y la mayoría de las vacantes no encajan
(piden presencial, otro idioma, otro país, skills que no se tienen). **Job Radar automatiza todo
ese trabajo**: rastrea, lee y filtra por vos, 24/7, y solo te avisa cuando encuentra algo que
realmente calza con tu perfil.

---

## 🏗️ Arquitectura

```
┌─ cron-job.org (cada 1h, disparo confiable vía API) ──┐   ┌─ GitHub Actions (cron backup) ─┐
└──────────────────────────┬───────────────────────────┘   └───────────────┬────────────────┘
                           ▼                                                ▼
              ╔═══════════════════════════════════════════════════════════════╗
              ║                       radar.py (orquestador)                    ║
              ╠═══════════════════════════════════════════════════════════════╣
              ║ 1. BUSCAR    12 portales en paralelo  ─────────► ~1.200 vacantes ║
              ║ 2. PREFILTRAR por keywords + DEDUP (seen.json) ─► solo nuevas    ║
              ║ 3. PRIORIZAR por nicho (automatización/IA primero)              ║
              ║ 4. EVALUAR — pipeline de IA de DOS NIVELES (ver abajo)          ║
              ║ 5. NOTIFICAR los matches a Telegram                             ║
              ║ 6. GUARDAR memoria de lo ya avisado (commit automático)         ║
              ╚═══════════════════════════════════════════════════════════════╝
```

### El pipeline de IA de dos niveles (el corazón del proyecto)

Los modelos de razonamiento ("thinking") dan el mejor juicio, pero se saturan (HTTP 429) cuando se
los usa para evaluar cientos de vacantes. La solución: **separar volumen de profundidad.**

| | **Nivel 1 — Screening** | **Nivel 2 — Lectura profunda** |
|---|---|---|
| **Modelo** | Llama 4 Maverick (rápido, confiable a escala) | Kimi K2.6 → fallback DeepSeek V4 Pro (razonamiento) |
| **Qué hace** | Evalúa **todas** las vacantes nuevas → acepta/descarta | Re-juzga los finalistas con análisis profundo |
| **Recursos** | Pool de 4 API keys, ~152 req/min | Pool de 2 keys dedicadas, ritmo bajo (sin 429) |

El Nivel 2 trabaja **en las dos direcciones**, corrigiendo los errores del screener rápido:

- 🧠 **Enriquece** cada match aceptado con un razonamiento más detallado.
- ⚠️ **Caza falsos positivos:** si el modelo profundo detecta un problema que el screener pasó por
  alto (ej. "es presencial"), lo marca con una nota — sin descartarlo (la persona decide).
- 🆘 **Rescata falsos negativos:** re-lee los rechazos *del nicho* y recupera los que el screener
  tumbó por error (ej. confundir una herramienta no-code con "desarrollo senior").

---

## 🔌 Los 12 portales

Cada portal es un *fetcher* independiente que normaliza al mismo contrato. Demuestra extracción de
datos por **múltiples técnicas**: REST/JSON, RSS, foros Discourse, APIs de búsqueda y endpoints no
documentados.

| Portal | Técnica de acceso |
|---|---|
| RemoteOK, Remotive, Jobicy, Working Nomads, Arbeitnow | API REST / JSON pública |
| We Work Remotely | Feed RSS por categoría |
| Himalayas, GetOnBrd | API JSON |
| Workana | Endpoint JSON interno (XHR, sin login) |
| LinkedIn | Guest Jobs API (público, sin login) |
| **n8n Community** | Foro Discourse vía JSON — *nicho exacto: gigs de automatización* |
| **Hacker News "Who is Hiring"** | Algolia Search API (thread mensual → posts de trabajo) |

> Cada fetcher **falla de forma segura** (si un portal cambia o cae, devuelve vacío y el radar
> sigue). El log muestra el desglose por portal en cada corrida (observabilidad).

---

## ⚙️ Decisiones de ingeniería destacadas

- **Selección de modelo basada en evidencia.** Construí un *golden-set* de evaluación
  (`comparar_modelos.py`) con vacantes de veredicto conocido para medir 8 LLMs. Kimi y DeepSeek
  ganaron en calidad (10/10) — **pero al validarlos a escala fallaban con 429 el ~79%.** Lección
  aplicada: *medir calidad con un set de prueba, pero validar el modelo en condiciones reales de
  volumen.* De ahí nació la arquitectura de dos niveles.
- **Ingeniería de rate-limit.** Round-robin sobre un pool de API keys con *throttle por key*
  (cada una respeta su propio límite de ~40 req/min), reintentos con *backoff* exponencial ante
  429/5xx, y timeouts agresivos para no colgarse.
- **Idempotencia y anti-duplicados.** Memoria persistente (`seen.json`) + dedup *cross-portal*
  dentro de cada corrida → nunca se avisa dos veces el mismo trabajo.
- **Robustez para correr solo 24/7.** Fetchers a prueba de fallos, modelos de *fallback*
  automáticos, y *push* de la memoria con `git pull --rebase` + reintentos (sobrevive a colisiones
  de commits).
- **Disparo confiable.** El cron de GitHub Actions atrasa/descarta corridas; se resolvió con un
  disparador externo (cron-job.org → `workflow_dispatch` API) que garantiza la cadencia.
- **Observabilidad.** Logs estructurados: desglose por portal, comparación screening-vs-profundo,
  conteo de rescates — todo auditable en cada corrida.
- **Prompt engineering.** El criterio de match vive en `criterios.txt` (perfil configurable):
  reglas de aceptación/descarte, *dealbreakers*, y salida forzada a JSON de una línea.

---

## 🧱 Estructura del proyecto

| Archivo | Rol |
|---|---|
| `radar.py` | Orquestador: buscar → filtrar → dedup → evaluar (2 niveles) → notificar → guardar |
| `portales.py` | Los 12 fetchers (un "agente de búsqueda" por portal), salida normalizada |
| `evaluar.py` | Pipeline de IA de dos niveles: pools de keys, throttle, screening + lectura profunda |
| `notificar.py` | Envío a Telegram (con manejo de rate limit) |
| `criterios.txt` | Perfil/criterios de match configurables (prompt del evaluador) |
| `seen.json` | Memoria de vacantes ya avisadas (anti-duplicados) |
| `comparar_modelos.py` | Banco de pruebas: evalúa N modelos contra un golden-set |
| `demo_thinking.py` | Demo: compara el razonamiento de screener vs modelos thinking |
| `.github/workflows/` | Automatización: cron del radar + commit de memoria |

---

## 📊 Resultados

- **~1.200 vacantes** rastreadas y analizadas por corrida, en **12 portales**.
- **Una corrida por hora**, 24/7, **sin servidor** y con **costo de infraestructura $0** (tiers
  gratuitos de GitHub Actions + NVIDIA NIM).
- **0 falsos avisos repetidos** gracias al dedup persistente.
- Matches entregados con **razonamiento de un modelo de razonamiento** sobre por qué encajan.

---

## 🛠️ Qué demuestra este proyecto

Orquestación de **LLMs en producción** · diseño de **pipelines de IA multi-modelo** · **evaluación
de modelos** (golden-set + pruebas a escala) · **prompt engineering** · **ingeniería de
rate-limiting** e integración de APIs · **automatización serverless** (GitHub Actions / cron) ·
Python con **concurrencia** y código defensivo · **extracción de datos** multi-fuente (REST, RSS,
Discourse, Algolia) · diseño de sistemas idempotentes, observables y tolerantes a fallos.

---

## ⚖️ Notas

Proyecto personal. Usa exclusivamente endpoints públicos / tiers gratuitos y respeta los límites de
cada servicio (ritmo humano, throttle por key). Los secretos (API keys, tokens) se manejan vía
GitHub Secrets, nunca en el código.

---

*Construido por **Hector Rodas** — Orquestación de IA y automatización · Python · n8n / Make · QA y evaluación de LLMs.*
