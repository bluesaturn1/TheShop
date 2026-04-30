# -*- coding: utf-8 -*-
"""
TheSHOP (www.shop.co.kr) product search.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlencode, urlparse

import requests
from requests.utils import requote_uri
from bs4 import BeautifulSoup

from config import (
    SHOP_BASE,
    SHOP_GOODS_AJAX_LIST,
    SHOP_GOODS_DTAIL_POPUP,
    SHOP_GOODS_SEARCH_FRAME,
    SHOP_GOODS_SEARCH_LIST,
)

BASE = SHOP_BASE
SEARCH_URL = SHOP_GOODS_SEARCH_LIST
SEARCH_FRAME_URL = SHOP_GOODS_SEARCH_FRAME
SEARCH_LIST_PATH = urlparse(SEARCH_URL).path
SEARCH_FRAME_PATH = urlparse(SEARCH_FRAME_URL).path

_MSG_MEMBER = "\uc68c\uc6d0\uc804\uc6a9\uc785\ub2c8\ub2e4"

# Form / search UI ? not product codes
_GOODS_CD_BLOCKLIST = frozenset(
    {
        "relevance",
        "goodsNm",
        "goodsnm",
        "goodsCode",
        "goodscode",
        "policyCd",
        "policycd",
        "parmIngre",
        "goodsDesc",
        "goodsdesc",
        "searchKey",
        "searchkey",
        "searchVal",
        "searchval",
        "orderBy",
        "orderby",
    }
)


def _is_plausible_goods_code(c: str) -> bool:
    c = (c or "").strip()
    if len(c) < 4 or len(c) > 40:
        return False
    if c.lower() in _GOODS_CD_BLOCKLIST:
        return False
    return True


DEFAULT_FORM = {
    "goodsInfoDataBean.orderBy": "relevance",
    "goodsInfoDataBean.rowPerPage": "15",
    "goodsInfoDataBean.ctgCd": "",
    "goodsInfoDataBean.mafcNm": "",
    "goodsInfoDataBean.goodsSalesType": "",
    "goodsInfoDataBean.searchKey": "goodsNm",
    "goodsInfoDataBean.searchVal": "",
}


def _ascii_only_cookie_header(cookie: str | None) -> str | None:
    """
    urllib3/httplib only accept header values in latin-1. Non-BMP or stray
    Unicode in pasted cookies breaks at encode time ? keep 7-bit ASCII only.
    (JSESSIONID, SCOUTER, etc. are ASCII.)
    """
    if not (cookie and cookie.strip()):
        return None
    s = "".join(c for c in cookie if ord(c) < 128)
    s = s.strip()
    if not s:
        return None
    # normalize single spaces after ;
    s = re.sub(r"\s*;\s*", "; ", s)
    return s


def _latin1_safe_http_headers(h: dict[str, str] | None) -> dict[str, str]:
    """All header values must be latin-1; coerce to ASCII-only if needed."""
    if not h:
        return {}
    out: dict[str, str] = {}
    for k, v in h.items():
        if v is None:
            continue
        s = str(v)
        try:
            s.encode("latin-1")
            out[k] = s
        except UnicodeEncodeError:
            out[k] = "".join(c for c in s if ord(c) < 128)
    return out


def _looks_like_empty_search(html: str) -> bool:
    return any(
        m in html
        for m in (
            "\uac80\uc0c9\uacb0\uacfc\uac00 \uc5c6",
            "\uc870\ud68c\ub41c \uc0c1\ud488\uc774 \uc5c6",
            "\uac80\uc0c9 \uacb0\uacfc\uac00 \uc5c6",
        )
    )


def _looks_like_login_block(html: str) -> bool:
    if _MSG_MEMBER in html and "login/logout" in html and len(html) < 20000:
        return True
    if "login/logout" in html and "goodsDtail" not in html and len(html) < 20000:
        if "alert(" in html or "location.href" in html:
            return True
    return False


def decode_html(resp: requests.Response) -> str:
    raw = resp.content
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_goods_list(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    # Prefer the canonical list table (contains real masterCd + price).
    # If we already have reliable rows here, return early to avoid mixing in
    # other heuristics that sometimes pick up non-product codes.
    for tr in soup.select("table.goobsList tbody tr"):
        code = (tr.get("alt") or "").strip()
        if not code:
            mic = tr.find("input", attrs={"name": "masterCdList"})
            if mic and (mic.get("value") or "").strip():
                code = mic.get("value", "").strip()
        tit = tr.select_one("a.titBTb")
        title = _norm_space(tit.get_text()) if tit else ""
        if not code:
            continue
        if not _is_plausible_goods_code(code):
            continue
        if code in seen:
            continue
        seen.add(code)
        pr = tr.select_one("span[id^='priceTd_']")
        price = _norm_space(pr.get_text()) if pr else ""
        # TheSHOP UI는 팝업으로 새 창을 띄우는 게 아니라,
        # /hos/shop/goodsSearchList.do?goodsCode= 로 들어가 오른쪽 패널을 갱신하는 형태다.
        detail_url = f"{SHOP_BASE}/hos/shop/goodsSearchList.do?goodsCode={code}"
        row: dict[str, str] = {
            "goodsCd": code,
            "title": title,
            "url": detail_url,
        }
        if price:
            row["price"] = price
        out.append(row)
    if out:
        return out

    for tag in soup.find_all(True):
        for k, v in (tag.attrs or {}).items():
            if k in ("data-goods-cd", "data-goodscd", "data-gdscd") and v and str(v).strip():
                c = str(v).strip()
                if c and _is_plausible_goods_code(c) and c not in seen:
                    seen.add(c)
                    out.append(
                        {
                            "goodsCd": c,
                            "title": _norm_space(
                                tag.get("title", "") or tag.get("alt", "") or ""
                            ),
                            "url": f"{SHOP_BASE}/hos/shop/goodsSearchList.do?goodsCode={c}",
                        }
                    )
    for inp in soup.find_all("input"):
        n = inp.get("name") or ""
        if not re.search(r"(^|\.)(goodsCd)$", n, re.I):
            continue
        val = (inp.get("value") or inp.get("data-value") or "").strip()
        if not val or not _is_plausible_goods_code(val):
            continue
        c = val
        if c in seen:
            continue
        seen.add(c)
        out.append(
            {
                "goodsCd": c,
                "title": "",
                "url": f"{SHOP_BASE}/hos/shop/goodsSearchList.do?goodsCode={c}",
            }
        )

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        hlow = href.lower()
        if (
            "goodsdetail" not in hlow
            and "goodsdtail" not in hlow
            and "goodscd" not in hlow
            and "goodsInfoDataBean.goodsCd" not in href
        ):
            continue
        if href.startswith("/"):
            full = urljoin(BASE, href)
        else:
            full = href
        u = href
        if "://" not in href:
            u = "https://dummy" + (href if href.startswith("/") else "/" + href)
        q = parse_qs(urlparse(u).query)
        codes = q.get("goodsInfoDataBean.goodsCd", []) or re.findall(
            r"goodsInfoDataBean\.goodsCd=([^&'\"]+)", href
        )
        goods_cd = unquote(codes[0]) if codes else ""
        if not _is_plausible_goods_code(goods_cd):
            continue
        if goods_cd and goods_cd in seen:
            continue
        if goods_cd:
            seen.add(goods_cd)
        title = _norm_space(a.get_text())
        if not title and a.img and a.img.get("alt"):
            title = _norm_space(a.img["alt"])
        out.append(
            {
                "goodsCd": goods_cd,
                "title": title,
                "url": full if full.startswith("http") else urljoin(BASE, href),
            }
        )

    if not out:
        for m in re.finditer(
            r"goodsInfoDataBean\.goodsCd=([A-Za-z0-9_-]+)[^'\"<]*>[\s\n]*([^<]+)<",
            html,
        ):
            code, title = m.group(1), _norm_space(m.group(2))
            if not _is_plausible_goods_code(code):
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append(
                {
                    "goodsCd": code,
                    "title": title,
                    "url": f"{SHOP_GOODS_DTAIL_POPUP}?goodsInfoDataBean.goodsCd={code}",
                }
            )

    return out


def _dedupe_by_code(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for it in items:
        c = (it.get("goodsCd") or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(it)
    return out


def _extract_goods_by_regex(html: str) -> list[dict[str, str]]:
    """Fallback: any goodsInfoDataBean.goodsCd= in page source (EUC-KR / iframe / minified)."""
    codes: list[str] = []
    for m in re.finditer(
        r"goodsInfoDataBean\.goodsCd=([A-Za-z0-9_-]+)", html, flags=re.IGNORECASE
    ):
        c = m.group(1)
        if _is_plausible_goods_code(c):
            codes.append(c)
    for m in re.finditer(r"[\?&]goodsCd=([A-Za-z0-9_-]+)(?:&|\"|\'|>|$)", html, re.I):
        c = m.group(1)
        if _is_plausible_goods_code(c):
            codes.append(c)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for c in codes:
        if not _is_plausible_goods_code(c):
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(
            {
                "goodsCd": c,
                "title": "",
                "url": f"{SHOP_GOODS_DTAIL_POPUP}?goodsInfoDataBean.goodsCd={c}",
            }
        )
    return out


def _augment_from_iframes(
    session: requests.Session, html: str, referer: str
) -> str:
    """Append iframe bodies when list is loaded in a child frame."""
    combined = [html]
    soup = BeautifulSoup(html, "html.parser")
    for f in soup.find_all("iframe"):
        src = (f.get("src") or "").strip()
        if not src or src.startswith("javascript:"):
            continue
        if "about:blank" in src:
            continue
        s = src.lower()
        if not any(
            k in s
            for k in ("goods", "search", "shop", "ifm", "list", "listframe", "gds")
        ):
            continue
        full = requote_uri(urljoin(BASE, src))
        try:
            r = session.get(
                full,
                timeout=30,
                headers=_latin1_safe_http_headers({"Referer": referer}),
            )
            combined.append(decode_html(r))
        except requests.RequestException:
            pass
    return "\n".join(combined)


def search_http(
    keyword: str, cookie: str | None, session: requests.Session | None = None
) -> tuple[requests.Response, str]:
    data = {**DEFAULT_FORM, "goodsInfoDataBean.searchVal": keyword}
    form_bytes = urlencode(data, doseq=True).encode("utf-8")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Origin": BASE,
        "Referer": f"{BASE}/",
        # charset only in body (bytes), not in header, to avoid any client quirks
        "Content-Type": "application/x-www-form-urlencoded",
    }
    safe_ck = _ascii_only_cookie_header(cookie)
    if safe_ck:
        headers["Cookie"] = safe_ck
    sess = session or requests.Session()
    safe_h = _latin1_safe_http_headers(headers)
    r = sess.post(SEARCH_URL, data=form_bytes, headers=safe_h, timeout=30)
    h1 = decode_html(r)
    h2_headers = _latin1_safe_http_headers(
        {**headers, "Referer": SEARCH_URL}
    )
    r2 = sess.post(
        SEARCH_FRAME_URL,
        data=form_bytes,
        headers=h2_headers,
        timeout=30,
    )
    h2 = decode_html(r2)
    h3 = ""
    try:
        h_ajax_headers = _latin1_safe_http_headers(
            {
                **headers,
                "Referer": SEARCH_URL,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        r3 = sess.post(
            SHOP_GOODS_AJAX_LIST,
            data=form_bytes,
            headers=h_ajax_headers,
            timeout=30,
        )
        h3 = decode_html(r3)
    except requests.RequestException:
        pass
    html = h1 + "\n" + h2 + "\n" + h3
    html = _augment_from_iframes(
        sess, html, referer=SEARCH_URL
    )
    return r, html


def _search_html_via_playwright(keyword: str) -> str | None:
    """
    Same form POST as search_http, but Playwright's request API sends cookies
    from the on-disk profile (no Python urllib3 Cookie header encoding).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    from config import SHOP_HEADLESS, USER_DATA_DIR

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {**DEFAULT_FORM, "goodsInfoDataBean.searchVal": keyword}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1280, "height": 720},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            r1 = ctx.request.post(SEARCH_URL, form=data, timeout=30_000)
            h1 = r1.text()
            r2 = ctx.request.post(
                SEARCH_FRAME_URL,
                form=data,
                timeout=30_000,
            )
            h2 = r2.text()
            h3 = ""
            try:
                r3 = ctx.request.post(
                    SHOP_GOODS_AJAX_LIST,
                    form=data,
                    timeout=30_000,
                )
                h3 = r3.text()
            except Exception:
                pass
            return h1 + "\n" + h2 + "\n" + h3
        except Exception:
            return None
        finally:
            ctx.close()


def _search_html_playwright_browser(keyword: str) -> str | None:
    """
    Real browser: open main (legacy form), fill search, submit. Product rows
    often appear only after JS/iframe; merge main + all frame HTML.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    from config import SHOP_BASE, SHOP_HEADLESS, USER_DATA_DIR

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.new_page()
            # Use the actual search page where topSearchForm + iframe(ifm) are guaranteed.
            page.goto(
                f"{SHOP_BASE}/hos/shop/goodsSearchList.do",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            inp = page.locator(
                'input[name="goodsInfoDataBean.searchVal"], #autoCompleteText'
            )
            if inp.count() == 0:
                return None
            inp.first.fill("", timeout=5_000)
            inp.first.fill(keyword, timeout=5_000)
            ok = page.evaluate(
                """
                (actionPath) => {
                  const f = document.topSearchForm
                    || document.querySelector('form.search_list');
                  if (!f) return false;
                  f.action = actionPath;
                  if (f.target) { f.removeAttribute('target'); }
                  f.submit();
                  return true;
                }
                """,
                SEARCH_LIST_PATH,
            )
            if not ok:
                for alt in (
                    "img[alt*='\uac80\uc0c9']",
                    "form.search_list a",
                    "a[onclick*=\"search2Goods\"]",
                ):
                    b = page.locator(alt)
                    if b.count() > 0:
                        try:
                            b.first.click(timeout=5_000)
                        except Exception:
                            continue
                        break
            time.sleep(1.0)
            try:
                page.wait_for_load_state("networkidle", timeout=90_000)
            except Exception:
                time.sleep(5.0)
            parts.append(page.content())
            for fr in page.frames:
                u = (fr.url or "").strip()
                if not u or u.startswith("about:blank") or u.startswith("data:"):
                    continue
                try:
                    parts.append(fr.content())
                except Exception:
                    pass
            return "\n".join(parts)
        except Exception:
            return None
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _form_inputs_html(data: dict[str, str]) -> str:
    out = []
    for k, v in data.items():
        out.append(
            f'<input type="hidden" name="{html_mod.escape(k, quote=True)}" '
            f'value="{html_mod.escape(str(v), quote=True)}" />'
        )
    return "\n".join(out)


def _search_html_playwright_auto_post(keyword: str) -> str | None:
    """
    Load empty page on shop origin, inject POST form + submit in-page (same
    session cookies). Catches result HTML that pure requests may not render.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    from config import SHOP_BASE, SHOP_HEADLESS, USER_DATA_DIR

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {**DEFAULT_FORM, "goodsInfoDataBean.searchVal": keyword}
    inputs = _form_inputs_html(data)
    inner = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/></head><body>
<form id="sf" method="post" action="{SEARCH_URL}">{inputs}</form>
</body></html>"""
    parts: list[str] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.new_page()
            page.goto(f"{SHOP_BASE}/", wait_until="domcontentloaded", timeout=90_000)
            page.set_content(inner, wait_until="domcontentloaded", timeout=30_000)
            page.evaluate(
                "() => { const f = document.getElementById('sf'); if (f) f.submit(); }"
            )
            try:
                page.wait_for_load_state("load", timeout=120_000)
            except Exception:
                time.sleep(15.0)
            try:
                page.wait_for_load_state("networkidle", timeout=45_000)
            except Exception:
                time.sleep(3.0)
            try:
                page.wait_for_selector(
                    "a[href*='goodsInfoDataBean.goodsCd'],a[href*='goodsDtail'],a[href*='goodscd']",
                    timeout=45_000,
                )
            except Exception:
                pass
            parts.append(page.content())
            for fr in page.frames:
                u = (fr.url or "").strip()
                if not u or u.startswith("about:blank") or u.startswith("data:"):
                    continue
                try:
                    parts.append(fr.content())
                except Exception:
                    pass
            h = "\n".join(parts)
            r2 = ctx.request.post(
                SEARCH_FRAME_URL,
                form=data,
                timeout=30_000,
            )
            h3 = ""
            try:
                r3 = ctx.request.post(
                    SHOP_GOODS_AJAX_LIST,
                    form=data,
                    timeout=30_000,
                )
                h3 = r3.text()
            except Exception:
                pass
            return h + "\n" + r2.text() + "\n" + h3
        except Exception:
            return None
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def obtain_cookie(*, force_playwright: bool = False) -> str | None:
    """
    Session for legacy /shop/ requests.
    If SHOP_ID+SHOP_PW exist, Playwright login is tried first (not stale SHOP_COOKIE).
    Use force_playwright=True to ignore SHOP_COOKIE and open the browser again.
    """
    from config import SHOP_COOKIE, SHOP_ID, SHOP_PW
    from theshop_login import login_cookie_header

    if force_playwright:
        if SHOP_ID and SHOP_PW:
            return login_cookie_header()
        return None
    if SHOP_ID and SHOP_PW:
        ck = login_cookie_header()
        if ck:
            return ck
    if SHOP_COOKIE:
        return SHOP_COOKIE
    return None


def run_search(keyword: str, cookie: str | None) -> dict:
    """Single search: returns dict with items or error keys."""
    from_requests = False
    html: str | None = None
    try:
        _, html = search_http(keyword, cookie, session=None)
        from_requests = True
    except (UnicodeEncodeError, UnicodeError):
        html = None
    except requests.RequestException:
        html = None
        from_requests = False
    if html is None or not str(html).strip():
        html = _search_html_via_playwright(keyword)
        from_requests = False
    if not html or not str(html).strip():
        return {
            "error": "http_failed",
            "items": [],
            "message": "requests failed and Playwright search also failed (run login once).",
        }
    if _looks_like_login_block(html):
        # requests로 받은 HTML이 로그인 차단이면,
        # (재로그인 직후/쿠키 인코딩 문제 등으로) requests에서는 계속 막힐 수 있어
        # Playwright 영구 프로필로 한 번 더 확인한다.
        if from_requests:
            html2 = _search_html_via_playwright(keyword)
            if html2 and html2.strip() and not _looks_like_login_block(html2):
                html = html2
                from_requests = False
            else:
                return {"error": "login_required", "items": []}
        else:
            return {"error": "login_required", "items": []}
    items = _dedupe_by_code(parse_goods_list(html))
    if not items:
        items = _dedupe_by_code(_extract_goods_by_regex(html))
    if not items and _looks_like_empty_search(html):
        return {"keyword": keyword, "count": 0, "items": []}
    if not items and from_requests:
        html2 = _search_html_via_playwright(keyword)
        if html2 and html2.strip() and html2 != html:
            if not _looks_like_login_block(html2):
                items = _dedupe_by_code(parse_goods_list(html2))
                if not items:
                    items = _dedupe_by_code(_extract_goods_by_regex(html2))
                if items:
                    html = html2
    if not items:
        html_ap = _search_html_playwright_auto_post(keyword)
        if html_ap and html_ap.strip() and not _looks_like_login_block(html_ap):
            items = _dedupe_by_code(parse_goods_list(html_ap))
            if not items:
                items = _dedupe_by_code(_extract_goods_by_regex(html_ap))
            if items:
                html = html_ap
    if not items:
        html3 = _search_html_playwright_browser(keyword)
        if html3 and html3.strip() and not _looks_like_login_block(html3):
            items = _dedupe_by_code(parse_goods_list(html3))
            if not items:
                items = _dedupe_by_code(_extract_goods_by_regex(html3))
            if items:
                html = html3
    if not items:
        if (os.getenv("THE_SHOP_DEBUG_HTML") or "").strip() in ("1", "true", "yes"):
            try:
                Path(__file__).resolve().parent.joinpath("last_search.html").write_text(
                    html, encoding="utf-8", errors="replace"
                )
            except OSError:
                pass
        return {
            "error": "parse_failed",
            "items": [],
            "html_sample": re.sub(r"\s+", " ", html[:5000]),
        }
    return {"keyword": keyword, "count": len(items), "items": items}


# -------------------------
# TheSHOP 상세(팝업) 품절/주문가능 확인
# -------------------------

_RE_TS_UNAVAIL_DETAIL = re.compile(
    r"품절|매진|일시[^가-힣]{0,8}품절|재고\s*없|단종|sold\s*out|품\s*절",
    re.I,
)


def fetch_goods_detail_popup_html(
    goods_cd: str,
    cookie: str | None,
    *,
    session: requests.Session | None = None,
) -> str:
    """
    TheSHOP 상세 팝업(goodsDtail) HTML fetch.
    cookie 는 obtain_cookie() 로 얻은 헤더 문자열을 그대로 넣는다.
    """
    c = (goods_cd or "").strip()
    if not c:
        return ""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{SHOP_BASE}/",
    }
    safe_ck = _ascii_only_cookie_header(cookie)
    if safe_ck:
        headers["Cookie"] = safe_ck
    url = requote_uri(f"{SHOP_GOODS_DTAIL_POPUP}?goodsInfoDataBean.goodsCd={c}")
    sess = session or requests.Session()
    r = sess.get(url, headers=_latin1_safe_http_headers(headers), timeout=45)
    r.raise_for_status()
    return decode_html(r)


def theshop_detail_is_orderable(html: str) -> tuple[bool | None, str]:
    """
    True: 주문/장바구니 가능으로 보임
    False: 품절/판매불가로 보임
    None: 로그인/파싱불가 등 신뢰 불가
    """
    if not html:
        return None, "empty_html"
    # Some goods codes return only a JS alert+close.
    # 이 경우가 항상 "품절/판매불가"는 아니어서(세션/권한/일시적 오류 등),
    # alert 문구가 '판매불가/품절'을 명시할 때만 False로 두고,
    # 그 외에는 불확실(None)로 취급해 필터 단계에서 누락되지 않게 한다.
    if len(html) < 1200 and "alert(" in html and "window.close" in html:
        # try to extract alert('...') message
        m = re.search(r"alert\(\s*['\"]([^'\"]+)['\"]\s*\)", html, re.I)
        msg = (m.group(1) if m else "").strip()
        if re.search(r"판매\s*되지|판매\s*중지|판매\s*불가|품절|매진", msg, re.I):
            return False, "popup_alert_unavailable"
        return None, "popup_alert_unknown"
    if _looks_like_login_block(html):
        return None, "login_required"
    if _RE_TS_UNAVAIL_DETAIL.search(html):
        return False, "unavail_text"

    # 장바구니/주문 버튼이 보이면 주문가능 쪽으로 판단
    # (사이트 DOM이 자주 바뀌므로 키워드/클래스 기반 휴리스틱)
    if re.search(r"장바구니|바로\s*구매|주문\s*하기", html):
        return True, "cta_text"
    if re.search(r"btn[_-]?add[_-]?cart|add[_-]?cart|cart", html, re.I) and not re.search(
        r"soldout|품절|매진", html, re.I
    ):
        return True, "cta_class_heuristic"

    # TheSHOP 상세 팝업은 버튼/문구가 케이스별로 달라 "주문가능" 신호를 못 찾는 경우가 있다.
    # 품절/판매불가 신호가 없으면 주문가능으로 간주(미탐 방지).
    return True, "no_unavail_marker"


def verify_theshop_items_with_detail(
    items: list[dict],
    cookie: str | None,
) -> list[dict]:
    """
    TheSHOP 규격필터로 걸러진 후보(items)를 상세 팝업으로 재확인.
    주문가능(True)만 반환. 불확실(None)은 제외(오탐 방지).
    """
    if not items:
        return []
    sess = requests.Session()
    out: list[dict] = []
    for it in items:
        gc = (it.get("goodsCd") or "").strip()
        if not gc:
            continue
        try:
            h = fetch_goods_detail_popup_html(gc, cookie, session=sess)
        except requests.RequestException:
            out.append({**it, "detailOk": False, "detailReason": "detail_fetch_failed"})
            continue
        ok, reason = theshop_detail_is_orderable(h)
        if ok is False:
            # 상세 팝업이 "판매불가/품절"로 보이더라도, 실제 목록 노출과 불일치/권한/세션 이슈가 있어
            # 모니터링 단계에서 완전히 누락되면 사용자 입장에선 '뜬 줄도 모르고' 지나갈 수 있다.
            # 따라서 제외하지 않고 표시만 남긴다(알림/목록에 포함되며 detailReason으로 구분 가능).
            out.append({**it, "detailOk": False, "detailReason": reason})
            continue
        if ok is True:
            out.append({**it, "detailOk": True, "detailReason": reason})
        else:
            # unknown → keep (list filter already excluded obvious 품절 문구)
            out.append({**it, "detailOk": False, "detailReason": reason})
    return out


def enrich_theshop_items_with_stock_qty(
    items: list[dict],
    *,
    keyword_for_ui: str | None = None,
) -> list[dict]:
    """
    TheSHOP UI(오른쪽 패널) 기준으로 재고(가능수량)를 읽어 items에 stockQty를 붙인다.

    - TheSHOP은 상품을 클릭하면 새 페이지/팝업이 아니라 iframe 내부 오른쪽 패널이 갱신된다.
    - requests만으로는 그 패널 로딩 로직(ajax + 세션 상태)을 안정적으로 재현하기 어려워,
      Playwright 브라우저로 검색→행 클릭→패널 DOM을 읽는 방식을 사용한다.
    """
    if not items:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return items

    from config import SHOP_BASE, SHOP_HEADLESS, USER_DATA_DIR

    # choose a keyword that guarantees the item row exists in list
    kw = (keyword_for_ui or "").strip()
    if not kw:
        kw = "일회용주사기"

    # map by goodsCd
    codes = [str((it.get("goodsCd") or "")).strip() for it in items]
    codes = [c for c in codes if c]
    if not codes:
        return items

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    stock_by_code: dict[str, int] = {}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=SHOP_HEADLESS,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.new_page()
            # Use the actual search page where #autoCompleteText + iframe(ifm) are guaranteed.
            page.goto(
                f"{SHOP_BASE}/hos/shop/goodsSearchList.do",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            inp = page.locator('#autoCompleteText, input[name="goodsInfoDataBean.searchVal"]')
            if inp.count() == 0:
                return items
            inp.first.fill("", timeout=5_000)
            inp.first.fill(kw, timeout=5_000)
            page.evaluate(
                """
                (actionPath) => {
                  const f = document.topSearchForm
                    || document.querySelector('form.search_list');
                  if (!f) return false;
                  f.action = actionPath;
                  f.target = "ifm";
                  f.submit();
                  return true;
                }
                """,
                SEARCH_FRAME_PATH,
            )
            # iframe ajax render
            time.sleep(4.0)

            # iframe "ifm" hosts list + right panel
            fr = page.frame(name="ifm")
            if not fr:
                # sometimes frame name is lost; pick by URL
                for f in page.frames:
                    if "goodsSearchListFrame.do" in (f.url or ""):
                        fr = f
                        break
            if not fr:
                return items

            # wait list rows
            try:
                fr.wait_for_selector("table.goobsList tbody tr[alt]", timeout=45_000)
            except Exception:
                return items

            for code in codes:
                if code in stock_by_code:
                    continue
                row = fr.locator(f"table.goobsList tbody tr[alt='{code}']")
                if row.count() == 0:
                    continue
                try:
                    row.first.click()
                except Exception:
                    continue
                # wait right panel update; parse HTML for digits near stock-ish tokens.
                try:
                    fr.wait_for_timeout(800)  # let ajax render
                except Exception:
                    pass
                try:
                    gd = fr.locator("#goodsDetail")
                    if gd.count() == 0:
                        continue
                    html = gd.inner_html()
                except Exception:
                    continue

                # Heuristics (most reliable first):
                # 1) In the right panel, the order row often has:
                #    <td id="goodsPrice">...</td><td>STOCK</td><td><input name="orderQty"...>
                #    We'll parse the TD immediately before the orderQty TD.
                n: int | None = None
                try:
                    soup = BeautifulSoup(html, "html.parser")
                    oq = soup.select_one("input#orderQty, input[name='orderQty']")
                    if oq:
                        td = oq.find_parent("td")
                        if td:
                            prev = td.find_previous_sibling("td")
                            if prev:
                                tx = re.sub(r"[^\d]", "", prev.get_text(" ", strip=True) or "")
                                if tx.isdigit():
                                    n = int(tx)
                except Exception:
                    n = None

                # 2) Fallback: explicit stock/qty markers in HTML/JS.
                if n is None:
                    m = re.search(
                        r"(?i)(stock|remain|qty|quantity)[^0-9]{0,20}([0-9]{1,6})",
                        html,
                    )
                    if not m:
                        m = re.search(r'(?i)max\\s*=\\s*\\"([0-9]{1,6})\\"', html)
                    if not m:
                        m = re.search(
                            r'(?i)(?:주문|구매)[^0-9]{0,30}([0-9]{1,6})\\s*(?:개|EA)',
                            html,
                        )
                    if m:
                        try:
                            n = int(m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1))
                        except Exception:
                            n = None

                if n is None:
                    continue
                if 0 <= n <= 999999:
                    stock_by_code[code] = n
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    if not stock_by_code:
        return items
    out: list[dict] = []
    for it in items:
        code = str((it.get("goodsCd") or "")).strip()
        if code and code in stock_by_code:
            out.append({**it, "stockQty": stock_by_code[code]})
        else:
            out.append(it)
    return out


def main() -> int:
    _default_kw = "\uc77c\uc68c\uc6a9\uc8fc\uc0ac\uae30"
    keyword = (sys.argv[1] if len(sys.argv) > 1 else _default_kw).strip()
    import config  # noqa: F401  # load .env before obtain_cookie
    cookie = obtain_cookie()
    if not cookie:
        print("No session: set SHOP_COOKIE or SHOP_ID+SHOP_PW for Playwright.", file=sys.stderr)
        return 1
    out = run_search(keyword, cookie)
    if out.get("error"):
        print(json.dumps(out, ensure_ascii=False, indent=2))
        e = out["error"]
        if e == "parse_failed":
            return 2
        if e == "http_failed":
            return 3
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
