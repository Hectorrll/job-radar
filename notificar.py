"""Envia mensajes a Telegram usando el bot de Hector."""
import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def enviar(texto):
    """Manda un mensaje de texto al chat de Hector. No rompe el radar si falla."""
    try:
        r = requests.post(
            API,
            json={
                "chat_id": CHAT_ID,
                "text": texto,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"# WARN telegram: {e}")
