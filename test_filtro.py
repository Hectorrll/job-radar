"""TEST de control (uso único): confirma que el criterio nuevo RECHAZA híbridos/presenciales/
otro-país/senior y ACEPTA los remotos buenos (incl. soporte con llamadas en español). Casos
sintéticos basados en la captura del 2026-06-11. Simula el flujo real del radar:
manda solo si Maverick ACEPTA y el thinking (Kimi) NO lo filtra."""
import evaluar

CASOS = [
    {"esperado": "RECHAZAR", "titulo": "Desenvolvedor de automacao n8n", "empresa": "TechBR",
     "ubicacion": "Brasil", "fuente": "Workana",
     "descripcion": "Procuramos um desenvolvedor de automacao com n8n para integrar APIs e construir "
     "fluxos de trabalho. Trabalho 100% remoto. Necessario portugues fluente. (idioma: portugues)"},
    {"esperado": "RECHAZAR", "titulo": "Automation Engineer (Full-time)", "empresa": "GlobalCorp",
     "ubicacion": "Remote", "fuente": "RemoteOK",
     "descripcion": "Full-time remote Automation Engineer. You will join daily standups, weekly team "
     "meetings and a video interview process. Excellent verbal English communication required."},
    {"esperado": "ACEPTAR", "titulo": "n8n workflow build (one-time gig)", "empresa": "SoloFounder",
     "ubicacion": "Remote", "fuente": "Upwork",
     "descripcion": "I need someone to build one n8n workflow that syncs a form to a spreadsheet and "
     "sends an email. Deliverable-based, fully async, communication over chat/written only. No calls."},
    {"esperado": "RECHAZAR", "titulo": "English Content Writer / Copywriter", "empresa": "BlogCo",
     "ubicacion": "Remote", "fuente": "WeWorkRemotely",
     "descripcion": "Native English content writer to produce high-quality blog articles and "
     "marketing copy in flawless, native-level English. Native English speakers only."},
    {"esperado": "ACEPTAR", "titulo": "Especialista en Automatizacion n8n (100% remoto)",
     "empresa": "Acme Latam", "ubicacion": "Remoto - LATAM", "fuente": "Workana",
     "descripcion": "Buscamos especialista en automatizacion con n8n para integrar APIs y construir "
     "workflows. 100% REMOTO, async, abierto a toda Latinoamerica. Trabajo en espanol."},
]


def main():
    print("# TEST FILTRO — criterio nuevo (Nivel 1 Maverick + Nivel 2 thinking)")
    print(f"# think activo: {evaluar.tiene_think()} | screener: {evaluar.MODEL}\n")
    ok = 0
    for c in CASOS:
        v = {k: c[k] for k in ("titulo", "empresa", "ubicacion", "fuente", "descripcion")}
        m = evaluar.evaluar_vacante(v)          # Nivel 1 (Maverick)
        k = evaluar.evaluar_profundo(v)         # Nivel 2 (Kimi -> DeepSeek)
        # flujo real del radar: manda solo si Maverick acepta Y el thinking no lo filtra
        manda = m["aceptar"] and (k is None or k["aceptar"])
        resultado = "MANDA" if manda else "FILTRA (no manda)"
        correcto = (resultado == "MANDA") == (c["esperado"] == "ACEPTAR")
        ok += 1 if correcto else 0
        print(f"[{c['esperado']}] {c['titulo'][:42]} | {c['ubicacion']}")
        print(f"   Nivel 1 Maverick: {'ACEPTA' if m['aceptar'] else 'descarta'} - {m['motivo'][:85]}")
        if k:
            print(f"   Nivel 2 thinking: {'ACEPTA' if k['aceptar'] else 'DESCARTA'} - {k['motivo'][:85]}")
        print(f"   >> RESULTADO: {resultado}  ({'✓ correcto' if correcto else '✗ MAL'})\n")
    print(f"# RESUMEN: {ok}/{len(CASOS)} correctos")


if __name__ == "__main__":
    main()
