"""Load .env from this project (same idea as Doctorville config)."""
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
# Doctorville .env(형제 폴더) — TheShop에 키가 없거나 **빈 값**일 때 TELEGRAM 등 보강
_custom = (os.environ.get("DOCTORVILLE_ENV_PATH") or "").strip()
if _custom:
    _dv_path = Path(_custom)
else:
    _dv_path = _ROOT.parent / "Doctorville" / ".env"
if _dv_path.is_file():
    load_dotenv(_dv_path, override=False)
    # TELEGRAM_* 가 TheSHOP .env에 "키만 있고 비어 있음"이면 load_dotenv(override=False)로는 못 덮어서, 파일에서 직접 읽어 채움
    _dvm = dotenv_values(_dv_path)
    for _k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not (os.environ.get(_k) or "").strip():
            _v = (_dvm.get(_k) or "").strip()
            if _v:
                os.environ[_k] = _v

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
        return ["2cc 23G", "3cc 23G", "5cc 23G"]
    parts: list[str] = []
    for chunk in raw.split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts if parts else ["2cc 23G", "3cc 23G", "5cc 23G"]


ALERT_PATTERNS = _parse_alert_patterns()
STATE_FILE = _ROOT / (os.getenv("THE_SHOP_STATE_FILE") or "theshop_monitor_state.json")


def _parse_drmro_alert_patterns() -> list[str]:
    """drmro 검색 규격 조각(부분): 기본은 THE_SHOP 과 동일하게 3cc·5cc."""
    raw = (os.getenv("DRMRO_ALERT_PATTERNS") or "").strip()
    if not raw:
        return ["2cc 23G", "3cc 23G", "5cc 23G"]
    parts: list[str] = []
    for chunk in raw.split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts if parts else ["2cc 23G", "3cc 23G", "5cc 23G"]


def _build_drmro_goods_search_queries() -> list[str]:
    """
    drmro goods_search.php 에 넣을 키워드 목록.
    - DRMRO_SEARCH_QUERIES: 쉼표로 구분한 **전체 검색문**(이 값이 있으면 다른 규격 env 무시)
    - 없으면: DRMRO_SEARCH_PREFIX + 각 DRMRO_ALERT_PATTERNS 조각 + DRMRO_SEARCH_SUFFIX
    """
    raw_full = (os.getenv("DRMRO_SEARCH_QUERIES") or "").strip()
    if raw_full:
        qs = [c.strip() for c in raw_full.split(",") if c.strip()]
        if qs:
            return qs
    prefix = (os.getenv("DRMRO_SEARCH_PREFIX") or "일회용주사기").strip()
    suffix = (os.getenv("DRMRO_SEARCH_SUFFIX") or "1inch").strip()
    queries: list[str] = []
    for part in _parse_drmro_alert_patterns():
        bits = [prefix, part, suffix]
        queries.append(" ".join(b for b in bits if b))
    return queries


DRMRO_GOODS_SEARCH_QUERIES = _build_drmro_goods_search_queries()
# TheSHOP+drmro 통합: 23G·1"·2/3/5cc 주문가능(이전 런 스냅샷과 달라질 때만 텔레그램, 기본 10분 간격은 THE_SHOP_CHECK_INTERVAL_MINUTES)
STOCK_NOTIFY_STATE_FILE = _ROOT / (
    os.getenv("STOCK_NOTIFY_STATE_FILE") or "stock_notify_state.json"
)
# false(기본): drmro 또는 theshop **한 쪽**만 2/3/5cc·23G1이 있어도 [추가/최초] 알림(검색어에 규격 맞는 theshop 0건인 경우에도 drmro만으로 알림).
# true: TheSHOP·drmro **각각** 1건 이상일 때만 [추가/최초] 알림(‘빠짐’만 있을 땐 항상 알림)
_snrb = (os.getenv("STOCK_NOTIFY_REQUIRE_BOTH_SITES") or "false").strip().lower()
STOCK_NOTIFY_REQUIRE_BOTH_SITES = _snrb in ("1", "true", "yes", "y")
# true면 ‘변화’ 텔레그램이 나갈 때 TheSHOP 규격목록(23G1·2/3/5cc)을 같은 메시지에 덧붙임(10분마다 별도 전송 아님)
TELEGRAM_FULL_LIST = (os.getenv("THE_SHOP_TELEGRAM_FULL_LIST") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
)

# drmro.com (닥터엠알오) — 로그인은 JS 암호화이므로 Playwright 권장, 또는 DRMRO_COOKIE
DRMRO_BASE = (os.getenv("DRMRO_BASE") or "https://drmro.com").strip().rstrip("/")
DRMRO_LOGIN_URL = (os.getenv("DRMRO_LOGIN_URL") or f"{DRMRO_BASE}/member/login.php").strip()
DRMRO_ID = (os.getenv("DRMRO_ID") or "").strip()
DRMRO_PW = (os.getenv("DRMRO_PW") or "").strip()
DRMRO_COOKIE = (os.getenv("DRMRO_COOKIE") or "").strip() or None
USER_DATA_DIR_DRMRO = _ROOT / (os.getenv("DRMRO_USER_DATA_DIR") or "playwright_data_drmro")
DRMRO_HEADLESS = (os.getenv("DRMRO_HEADLESS", "true") or "true").strip().lower() == "true"
DRMRO_GOODS_SEARCH = f"{DRMRO_BASE}/goods/goods_search.php"
# 상품상세(goods_view)로 재고·품절 재확인 (검색리스트는 품절과 불일치할 수 있음)
_dv = (os.getenv("DRMRO_VERIFY_DETAIL") or "true").strip().lower()
DRMRO_VERIFY_DETAIL = _dv in ("1", "true", "yes")
try:
    DRMRO_DETAIL_DELAY_SEC = float((os.getenv("DRMRO_DETAIL_DELAY_SEC") or "0.2").strip())
except ValueError:
    DRMRO_DETAIL_DELAY_SEC = 0.2
