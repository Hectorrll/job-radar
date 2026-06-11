"""TEST de control (uso único): confirma que el criterio nuevo RECHAZA híbridos/presenciales/
otro-país/senior y ACEPTA los remotos buenos (incl. soporte con llamadas en español). Casos
sintéticos basados en la captura del 2026-06-11. Simula el flujo real del radar:
manda solo si Maverick ACEPTA y el thinking (Kimi) NO lo filtra."""
import evaluar

CASOS = [
    {"esperado": "RECHAZAR", "titulo": "Agentic AI Engineer", "empresa": "Flat Rock Technology",
     "ubicacion": "Heredia, Costa Rica", "fuente": "LinkedIn",
     "descripcion": "Agentic AI Engineer to join our team in Heredia, Costa Rica. This is a "
     "HYBRID role requiring 3 days per week on-site at our Heredia office. Build AI agents."},
    {"esperado": "RECHAZAR", "titulo": "Generative AI Engineer", "empresa": "Kuona",
     "ubicacion": "Monterrey, Nuevo Leon, Mexico", "fuente": "LinkedIn",
     "descripcion": "Senior Generative AI Engineer, on-site/hybrid in Monterrey, Mexico. 5+ years "
     "of software engineering, strong backend and ML systems experience required."},
    {"esperado": "ACEPTAR", "titulo": "Especialista en Automatizacion n8n (100% remoto)",
     "empresa": "Acme Latam", "ubicacion": "Remoto - LATAM", "fuente": "Workana",
     "descripcion": "Buscamos especialista en automatizacion con n8n para integrar APIs y construir "
     "workflows. 100% REMOTO, async, abierto a toda Latinoamerica. Trabajo en espanol."},
    {"esperado": "ACEPTAR", "titulo": "Soporte al Cliente bilingue (remoto)", "empresa": "HelpCo",
     "ubicacion": "Remoto", "fuente": "RemoteOK",
     "descripcion": "Atencion al cliente 100% REMOTA: chat, email y LLAMADAS EN ESPANOL. Ingles "
     "solo ESCRITO para documentacion. NO se requiere hablar ingles."},
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
