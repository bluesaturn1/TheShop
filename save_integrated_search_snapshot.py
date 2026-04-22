# -*- coding: utf-8 -*-
"""the.shop.co.kr 통합검색 결과 페이지를 스냅샷으로 저장 (Playwright, 기존 프로필)."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from urllib.parse import urlparse

from config import SHOP_GOODS_SEARCH_FRAME, SHOP_HEADLESS, USER_DATA_DIR

FRAME_PATH = urlparse(SHOP_GOODS_SEARCH_FRAME).path  # e.g. /hos/shop/goodsSearchListFrame.do

# 통합 쇼핑몰 엔트리(요청: the.shop.co.kr)
ENTRY_URL = "https://the.shop.co.kr/"

_RELPATH = "integrated_search_일회용주사기.html"
_ROOT = Path(__file__).resolve().parent


def main() -> int:
    kw = "일회용주사기"
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_main = _ROOT / _RELPATH
    out_frame = _ROOT / "integrated_search_iframe_goodsList.html"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.new_page()
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=120_000)
            time.sleep(1.5)
            for btn_txt in ("오늘 하루 안보기", "닫기", "닫기", "close"):
                try:
                    b = page.get_by_role("button", name=btn_txt)
                    if b.count() > 0:
                        b.first.click(timeout=2_000)
                        time.sleep(0.3)
                except Exception:
                    pass
            # www 레거시 통합검색 폼
            inp = page.locator(
                'input#autoCompleteText, input[name="goodsInfoDataBean.searchVal"]'
            )
            # the.shop.co.kr (Next) 헤더 검색
            if inp.count() == 0:
                inp = page.locator(
                    "[class*='header_search_box'] input, "
                    "header input[type='text'], "
                    "header input[placeholder]"
                )
            if inp.count() == 0:
                out_main.write_text(
                    page.content(), encoding="utf-8", errors="replace"
                )
                return 2
            inp.first.wait_for(state="visible", timeout=20_000)
            inp.first.fill("", timeout=10_000)
            inp.first.fill(kw, timeout=10_000)
            # 레거시: iframe 제출
            ok = page.evaluate(
                """
                ([actionPath, kw]) => {
                  const f = document.topSearchForm
                    || document.querySelector('form#topSearchForm')
                    || document.querySelector('form.search_list');
                  if (!f) return false;
                  const el = f.elements && f.elements['goodsInfoDataBean.searchVal'];
                  if (el) { el.value = kw; }
                  f.target = 'ifm';
                  f.action = actionPath;
                  f.submit();
                  return true;
                }
                """,
                [FRAME_PATH, kw],
            )
            if not ok:
                inp.first.press("Enter")
            time.sleep(2.0)
            try:
                page.wait_for_load_state("networkidle", timeout=90_000)
            except Exception:
                time.sleep(8.0)
            # www: iframe #goodsList
            for _ in range(30):
                fr = page.frame(name="ifm")
                if fr:
                    try:
                        fr.wait_for_selector(
                            "#goodsList",
                            state="attached",
                            timeout=5_000,
                        )
                        g = fr.locator("#goodsList")
                        if g.count() and g.first.inner_text(timeout=2_000).strip():
                            break
                    except Exception:
                        pass
                time.sleep(1.0)
            # the.shop.co.kr: 검색 후 리스트(카드) 로딩 대기
            try:
                page.wait_for_selector(
                    "[class*='product'], a[href*='/goods/'], [class*='goods_']",
                    timeout=60_000,
                )
            except Exception:
                time.sleep(5.0)
            html = page.content()
            out_main.write_text(html, encoding="utf-8", errors="replace")
            fr = page.frame(name="ifm")
            if fr:
                try:
                    gl = fr.locator("#goodsList")
                    if gl.count():
                        body = gl.first.inner_html()
                    else:
                        body = fr.content()
                    out_frame.write_text(
                        f"<!-- iframe name=ifm -->\n{body}",
                        encoding="utf-8",
                        errors="replace",
                    )
                except Exception as e:
                    out_frame.write_text(
                        f"<!-- could not read iframe: {e} -->\n{fr.content()}",
                        encoding="utf-8",
                        errors="replace",
                    )
            return 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
