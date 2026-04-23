"""drmro.com 로그인 (Playwright) — login_ps.php 는 CryptoJS로 ID/PW 암호화 후 POST."""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from config import (
    DRMRO_BASE,
    DRMRO_HEADLESS,
    DRMRO_ID,
    DRMRO_LOGIN_URL,
    DRMRO_PW,
    USER_DATA_DIR_DRMRO,
)


def _cookies_to_header(cookies: list[dict], host: str = "drmro.com") -> str:
    parts: list[str] = []
    for c in cookies:
        name = c.get("name")
        if not name:
            continue
        value = c.get("value", "")
        dom = (c.get("domain") or "").lstrip(".")
        if host in dom or dom.endswith("drmro.com"):
            parts.append(f"{name}={value}")
    if not parts:
        for c in cookies:
            n = c.get("name")
            if n:
                parts.append(f"{n}={c.get('value', '')}")
    return "; ".join(parts)


def login_cookie_header() -> str | None:
    """
    drmro.com 세션용 Cookie 헤더 값.
    member/login.php → #formLogin + CryptoJS(페이지) → login_ps.php
    """
    if not DRMRO_ID or not DRMRO_PW:
        return None
    USER_DATA_DIR_DRMRO.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR_DRMRO),
            headless=DRMRO_HEADLESS,
            viewport={"width": 1280, "height": 720},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(
                DRMRO_LOGIN_URL, wait_until="domcontentloaded", timeout=90_000
            )
            time.sleep(1.0)
            if not page.locator("#loginId").count():
                return None
            page.fill("#loginId", DRMRO_ID)
            page.fill("#loginPwd", DRMRO_PW)
            try:
                with page.expect_navigation(
                    wait_until="domcontentloaded", timeout=120_000
                ):
                    page.locator("form#formLogin button.member_login_order_btn").first.click()
            except PlaywrightTimeout:
                time.sleep(2.0)
            u = (page.url or "").lower()
            if "login" in u and "member" in u:
                try:
                    if page.locator(".js_caution_msg1").is_visible(timeout=2_000):
                        return None
                except Exception:
                    pass
            try:
                page.goto(
                    f"{DRMRO_BASE}/main/index.php",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                time.sleep(0.5)
            except Exception:
                pass
            hdr = _cookies_to_header(ctx.cookies())
            return hdr if hdr and hdr.strip() else None
        finally:
            ctx.close()
