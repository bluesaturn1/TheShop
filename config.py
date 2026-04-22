"""Load .env from this project (same idea as Doctorville config)."""
import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
# Optional: same machine — reuse Doctorville .env for MIMS/telegram when keys missing here
_dv = _ROOT.parent / "Doctorville" / ".env"
if _dv.is_file():
    load_dotenv(_dv, override=False)

# MIMS (same account as Doctorville if you use Mcircle)
SHOP_ID = (os.getenv("SHOP_ID") or os.getenv("DOCTORVILLE_ID") or "").strip()
SHOP_PW = (os.getenv("SHOP_PW") or os.getenv("DOCTORVILLE_PW") or "").strip()

SHOP_BASE = (os.getenv("SHOP_BASE") or "https://www.shop.co.kr").strip().rstrip("/")
SHOP_LOGIN_URL = (os.getenv("SHOP_LOGIN_URL") or f"{SHOP_BASE}/front/intro/login").strip()
# hos=병의원(통합) 몰: https://www.shop.co.kr/hos/shop/goodsSearchList.do
# 비우면 구경로: .../shop/goodsSearchList.do  ( .env SHOP_GOODS_PREFIX=  로 비활성 )
if "SHOP_GOODS_PREFIX" in os.environ:
    _gp = (os.environ.get("SHOP_GOODS_PREFIX") or "").strip().strip("/")
else:
    _gp = "hos"
SHOP_GOODS_BASE = f"{SHOP_BASE}/{_gp}/shop" if _gp else f"{SHOP_BASE}/shop"
SHOP_GOODS_SEARCH_LIST = f"{SHOP_GOODS_BASE}/goodsSearchList.do"
SHOP_GOODS_SEARCH_FRAME = f"{SHOP_GOODS_BASE}/goodsSearchListFrame.do"
# iframe #goodsList 를 채우는 Ajax (jQuery .load) — requests만으로는 여기 HTML이 없으면 파싱 실패
SHOP_GOODS_AJAX_LIST = (
    f"{SHOP_BASE}/{_gp}/ajax/goodsSearchListEgAjax.do"
    if _gp
    else f"{SHOP_BASE}/ajax/goodsSearchListEgAjax.do"
)
# 상세 팝업 (상품코드 링크 합성용; 사이트가 내려주는 href가 있으면 그걸 우선)
SHOP_GOODS_DTAIL_POPUP = (
    f"{SHOP_BASE}/{_gp}/popup/goodsDtail.do" if _gp else f"{SHOP_BASE}/popup/goodsDtail.do"
)

# Optional: set manually instead of Playwright login
SHOP_COOKIE = (os.getenv("SHOP_COOKIE") or "").strip() or None

# Telegram (same variable names as Doctorville)
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

# Playwright
USER_DATA_DIR = _ROOT / "playwright_data_theshop"
SHOP_HEADLESS = (os.getenv("SHOP_HEADLESS", "true") or "true").strip().lower() == "true"

# Monitor (default: syringe product name)
_DEFAULT_SHOP_KEYWORD = "\uc77c\uc68c\uc6a9\uc8fc\uc0ac\uae30"
SEARCH_KEYWORD = (os.getenv("THE_SHOP_SEARCH_KEYWORD") or _DEFAULT_SHOP_KEYWORD).strip()
try:
    CHECK_INTERVAL_MINUTES = int((os.getenv("THE_SHOP_CHECK_INTERVAL_MINUTES") or "10").strip())
except ValueError:
    CHECK_INTERVAL_MINUTES = 10

# 알림(부분일치): 기본 3cc 23G, 5cc 23G — 쉼표로 구분 (공백 포함 문구는 큰따옴표로)
def _parse_alert_patterns() -> list[str]:
    raw = (os.getenv("THE_SHOP_ALERT_PATTERNS") or "").strip()
    if not raw:
        return ["3cc 23G", "5cc 23G"]
    parts: list[str] = []
    for chunk in raw.split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts if parts else ["3cc 23G", "5cc 23G"]


ALERT_PATTERNS = _parse_alert_patterns()
STATE_FILE = _ROOT / (os.getenv("THE_SHOP_STATE_FILE") or "theshop_monitor_state.json")
# "true"면 검색 전체 요약을 매번 보냄(과거 동작). 기본은 알림(키워드 매칭)만.
TELEGRAM_FULL_LIST = (os.getenv("THE_SHOP_TELEGRAM_FULL_LIST") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
