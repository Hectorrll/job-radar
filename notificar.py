"""Envia mensajes a Telegram usando el bot de Hector.
Maneja el rate limit de Telegram (429) con espera + reintento, y pausa entre
mensajes para no saturar.
"""
import os
import time
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def enviar(texto):
    """Manda un mensaje. Si Telegram limita (429), espera y reintenta."""
    for intento in range(4):
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
            if r.status_code == 429:
                espera = r.json().get("parameters", {}).get("retry_after", 3)
                time.sleep(espera + 1)
                continue
            r.raise_for_status()
            time.sleep(1.2)  # respetar el limite de Telegram entre mensajes
            return
        except Exception as e:
            if intento < 3:
                time.sleep(3)
                continue
            print(f"# WARN telegram: {e}")
            return
