"""Telegram send (env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) — same as Doctorville pattern."""
import json
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_TELEGRAM_TIMEOUT = (15, 45)
_TELEGRAM_RETRIES = 3
_TELEGRAM_RETRY_DELAY = 2.0


def _send_message_http(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    tok = "".join(c for c in str(TELEGRAM_BOT_TOKEN) if 32 <= ord(c) < 127)
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    chat = str(TELEGRAM_CHAT_ID).strip()
    payload = {
        "chat_id": chat,
        "text": text,
        "disable_web_page_preview": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json; charset=utf-8"}
    for attempt in range(1, _TELEGRAM_RETRIES + 1):
        try:
            r = requests.post(url, data=body, headers=hdrs, timeout=_TELEGRAM_TIMEOUT)
            if r.status_code != 200:
                try:
                    err = r.json()
                    print(f"[telegram] {err.get('description', r.text)}")
                except Exception:
                    print(f"[telegram] {r.status_code} {r.text[:200]}")
                return False
            return True
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < _TELEGRAM_RETRIES:
                time.sleep(_TELEGRAM_RETRY_DELAY)
            else:
                print(f"[telegram] {e}")
    return False


def send_message(text: str) -> bool:
    if not text or not str(text).strip():
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    return _send_message_http(text)


def chunk_telegram_text(text: str, limit: int = 4000) -> list[str]:
    """Split for Telegram 4096 limit (leave margin)."""
    t = text.strip()
    if len(t) <= limit:
        return [t] if t else []
    out: list[str] = []
    while t:
        out.append(t[:limit])
        t = t[limit:].lstrip()
    return out
