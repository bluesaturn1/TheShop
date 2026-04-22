"""Telegram test (Doctorville and TheSHOP use the same TELEGRAM_* env names)."""
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from telegram_notify import send_message


def main() -> None:
    print("Chat ID:", TELEGRAM_CHAT_ID or "(empty)")
    print("Token:", (TELEGRAM_BOT_TOKEN[:16] + "...") if TELEGRAM_BOT_TOKEN else "(empty)")
    print()
    ok = send_message("[TheSHOP] Telegram test")
    if ok:
        print("OK")
    else:
        print("Failed — check .env and chat /start with the bot.")


if __name__ == "__main__":
    main()
