"""TheSHOP login via Playwright (MIMS on shop login page — same flow as browser $.login)."""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from config import (
    SHOP_BASE,
    SHOP_HEADLESS,
    SHOP_ID,
    SHOP_LOGIN_URL,
    SHOP_PW,
    USER_DATA_DIR,
)


def _wait_away_from_login_url(page, max_wait_s: int = 120) -> bool:
    """MIMS may redirect a moment after JS sets location.href."""
    for _ in range(max_wait_s):
        u = (page.url or "").strip()
        if "/front/intro/login" not in u:
            return True
        time.sleep(1)
    return "/front/intro/login" not in (page.url or "")


def _fill_credentials_if_present(page) -> bool:
    """로그인 페이지에서 ID/PW 필드가 보이면 env 값으로 재입력."""
    try:
        if page.locator("#userId").count() == 0 or page.locator("#userPwd").count() == 0:
            return False
    except Exception:
        return False

    try:
        page.fill("#userId", SHOP_ID)
    except Exception:
        # 필드가 렌더링 직후라 fill 타이밍이 어긋나는 경우가 있어 재시도용
        pass
    try:
        page.fill("#userPwd", SHOP_PW)
    except Exception:
        pass
    return True


def _click_login_if_possible(page) -> bool:
    """로그인 버튼(또는 $.login() 호출 요소)을 찾으면 클릭."""
    candidates = [
        "a[onclick*=\"$.login()\"]",
        "button[onclick*=\"$.login()\"]",
        "input[onclick*=\"$.login()\"]",
        # 텍스트 기반(사이트 DOM 변경 대비)
        "text=로그인",
        "text=LOGIN",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=3_000)
                return True
        except Exception:
            continue
    return False


def _settle_session_on_site(page) -> None:
    """So legacy /shop/ JSESSIONID matches the same browser session."""
    try:
        page.goto(
            f"{SHOP_BASE}/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        time.sleep(1.0)
    except Exception:
        pass


def _cookies_to_header(cookies: list[dict]) -> str:
    parts: list[str] = []
    for c in cookies:
        name = c.get("name")
        if not name:
            continue
        value = c.get("value", "")
        dom = (c.get("domain") or "").lstrip(".")
        if "shop.co.kr" in dom or dom.endswith("www.shop.co.kr"):
            parts.append(f"{name}={value}")
    if not parts:
        for c in cookies:
            n = c.get("name")
            if n:
                parts.append(f"{n}={c.get('value', '')}")
    return "; ".join(parts)


def login_cookie_header() -> str | None:
    """
    Return Cookie header value for https://www.shop.co.kr
    Uses persistent profile (USER_DATA_DIR) so the next run may skip typing if session is alive.
    """
    if not SHOP_ID or not SHOP_PW:
        return None
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1280, "height": 720},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(SHOP_LOGIN_URL, wait_until="domcontentloaded", timeout=90_000)
            time.sleep(1.5)

            # 로그인 페이지가 다시 떠도(보안확인 후 리다이렉트/재렌더링),
            # env 값으로 ID/PW를 자동 재입력하고 로그인 버튼을 재클릭한다.
            max_attempts = 6
            for _ in range(max_attempts):
                u = (page.url or "").strip()
                # URL이 로그인 페이지이거나, 폼 필드가 존재하면 재시도
                if "/front/intro/login" in u or page.locator("#userId").count() > 0:
                    _fill_credentials_if_present(page)
                    _click_login_if_possible(page)
                    # 리다이렉트/자동전환이 일어나면 URL이 바뀐다.
                    if _wait_away_from_login_url(page, max_wait_s=25):
                        break
                else:
                    break
                time.sleep(2.0)
            _settle_session_on_site(page)

            # 로그인 페이지 URL에 남아있더라도(일부 사이트는), 쿠키가 갱신되어 있으면
            # 일단 쿠키를 반환하고 상위(검색)에서 login_required 여부로 재시도/판단하게 한다.
            if "/front/intro/login" in (page.url or ""):
                # 명시적 로그인 실패 요소가 보이면 즉시 실패로 처리
                try:
                    if page.locator("#failDiv").is_visible():
                        return None
                except Exception:
                    pass

                # 그래도 URL이 남아있으면, 리다이렉트 대기(기존 20초보다 넉넉히)
                _wait_away_from_login_url(page, max_wait_s=60)

            hdr = _cookies_to_header(ctx.cookies())
            return hdr if hdr and hdr.strip() else None
        finally:
            ctx.close()
