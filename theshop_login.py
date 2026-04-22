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
            need_form = bool(
                page.locator("#userId").count() > 0
                and page.locator("#userId").first.is_visible(timeout=5_000)
            )
            if need_form:
                page.fill("#userId", SHOP_ID)
                page.fill("#userPwd", SHOP_PW)
                try:
                    with page.expect_navigation(timeout=120_000, wait_until="domcontentloaded"):
                        page.locator("a[onclick*=\"$.login()\"]").first.click()
                except PlaywrightTimeout:
                    pass
                _wait_away_from_login_url(page, max_wait_s=90)
            else:
                if "/front/intro/login" in page.url:
                    time.sleep(2.0)
            if "/front/intro/login" in (page.url or ""):
                try:
                    if page.locator("#failDiv").is_visible():
                        return None
                except Exception:
                    pass
                if not _wait_away_from_login_url(page, max_wait_s=20):
                    return None
            if "/front/intro/login" in (page.url or ""):
                return None
            _settle_session_on_site(page)
            hdr = _cookies_to_header(ctx.cookies())
            return hdr if hdr and hdr.strip() else None
        finally:
            ctx.close()
