# -*- coding: utf-8 -*-
"""drmro.com goods_search.php — GET 파싱, 품절(SOLD OUT) 제외, 규격 필터."""
from __future__ import annotations

import re
import sys
import time
from typing import Any
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from config import DRMRO_BASE, DRMRO_GOODS_SEARCH


def decode_html(resp: requests.Response) -> str:
    raw = resp.content
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def is_sold_out_item(li_tag) -> bool:
    c = (li_tag.get("class") or [])
    if "item_soldout" in c:
        return True
    box = li_tag.select_one("div.item_cont .item_soldout_bg")
    if box is not None:
        return True
    return False


def parse_goods_list(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, str]] = []
    for li in soup.select("div.goods_list_cont li"):
        if not li.select_one("div.item_cont"):
            continue
        cont = li.select_one("div.item_cont")
        if cont is None:
            continue
        a = cont.select_one("div.item_tit_box a[href*='goodsNo=']")
        if not a or not a.get("href"):
            a = cont.select_one('a[href*="goods_view.php?goodsNo="]')
        if not a or not a.get("href"):
            continue
        href = a["href"].strip()
        full = href if href.startswith("http") else urljoin(f"{DRMRO_BASE}/", href)
        mno = re.search(r"goodsNo=(\d+)", href, re.I)
        goods_no = mno.group(1) if mno else ""
        title_el = cont.select_one("strong.item_name")
        title = _norm(title_el.get_text()) if title_el else ""
        spec_parts: list[str] = []
        for sp in cont.select("div.item_number_box span.num_code"):
            t = _norm(sp.get_text())
            if t.startswith("규격 :") or t.startswith("규격:"):
                spec_parts.append(t.split(":", 1)[-1].strip())
        spec = " | ".join(spec_parts) if spec_parts else ""
        product_code = ""
        for sp in cont.select("div.item_number_box span.num_code"):
            tx = _norm(sp.get_text())
            if "상품코드" in tx or "모델번호" in tx:
                m = re.search(
                    r"(?:상품코드|모델번호)\s*:\s*([A-Za-z0-9._\-]+)", tx, re.I
                )
                if m:
                    product_code = m.group(1)
                    break
        price_el = cont.select_one("strong.item_price span")
        price = _norm(price_el.get_text()) if price_el else ""
        brand_el = cont.select_one("span.item_brand")
        brand = _norm(brand_el.get_text()) if brand_el else ""
        out.append(
            {
                "goodsNo": goods_no,
                "title": title,
                "spec": spec,
                "productCode": product_code,
                "price": price,
                "brand": brand,
                "url": full,
                "soldOut": "1" if is_sold_out_item(li) else "0",
            }
        )
    return out


def _ascii_cookie(cookie: str | None) -> str | None:
    if not (cookie and cookie.strip()):
        return None
    s = "".join(c for c in cookie if ord(c) < 128)
    s = s.strip()
    if not s:
        return None
    s = re.sub(r"\s*;\s*", "; ", s)
    return s


def search_get(keyword: str, cookie: str | None) -> str:
    q = quote(keyword, safe="")
    url = f"{DRMRO_GOODS_SEARCH}?keyword={q}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    ck = _ascii_cookie(cookie)
    if ck:
        headers["Cookie"] = ck
    r = requests.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    return decode_html(r)


# 규격: 2|3|5 + ml|cc, 23G, 1 inch (×/x/공백 허용)
_RE_VOL = re.compile(
    # NOTE: TheSHOP 제목에 `3CC23G1inch`처럼 규격이 붙어서 나오는 케이스가 있어
    # `CC` 뒤 단어경계(\b)를 강제하면 매칭이 실패한다. 뒤가 숫자/문자여도 허용.
    r"(?P<vol>[235])\s*(?:ml|mL|ML|cc|CC|Cc)",
    re.I,
)
_RE_23G = re.compile(r"23\s*G", re.I)
_RE_1IN = re.compile(
    r"1\s*inch|1inch|1-in|1\s*in\.?\b",
    re.I,
)


def spec_matches_23g_1inch_235ml(text: str) -> tuple[int | None, bool]:
    """
    (용량 2/3/5 중 하나, 전체 규격이 조건에 맞는지).
    23G 와 1inch 가 같이 있어야 하며, 2·3·5 ml/cc 중 하나만 인정(첫 일치).
    """
    t = (text or "").replace("×", "x")
    if not _RE_23G.search(t) or not _RE_1IN.search(t):
        return None, False
    m = _RE_VOL.search(t)
    if not m:
        return None, False
    vol = int(m.group("vol"))
    if vol not in (2, 3, 5):
        return None, False
    return vol, True


def filter_orderable_and_spec(
    items: list[dict[str, Any]],
    *,
    exclude_soldout: bool = True,
) -> list[dict[str, Any]]:
    r: list[dict[str, Any]] = []
    for it in items:
        if exclude_soldout and it.get("soldOut") == "1":
            continue
        spec = f"{it.get('title', '')} {it.get('spec', '')}"
        vol, ok = spec_matches_23g_1inch_235ml(spec)
        if not ok or vol is None:
            continue
        row = {**it, "volumeMl": vol}
        r.append(row)
    return r


_RE_UNAVAIL = re.compile(
    r"품절|매진|일시[^가-힣]{0,8}품절|재고\s*없|단종|sold\s*out|품\s*절",
    re.I,
)


def theshop_text_likely_unavailable(text: str) -> bool:
    """TheSHOP 목록/제목에 나오는 품절·매진 류(휴리스틱)."""
    return bool(_RE_UNAVAIL.search(text or ""))


def filter_theshop_syringe_23g1_235cc(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    theshop.co.kr 검색 행: 제목·코드에 2/3/5cc(ml) + 23G + 1inch, 품절 문구 제외.
    """
    r: list[dict[str, Any]] = []
    for it in items:
        text = f"{it.get('title', '')} {it.get('goodsCd', '')}"
        if theshop_text_likely_unavailable(text):
            continue
        vol, ok = spec_matches_23g_1inch_235ml(text)
        if not ok or vol is None:
            continue
        r.append({**it, "volumeMl": vol, "source": "theshop"})
    return r


# --- goods_view.php: 검색·리스트와 다를 수 있는 실제 품절/재고 ---

_RE_SOLDOUT_FL = re.compile(
    r"soldOutFl\s*[:=]\s*['\"]?([yn])\b",
    re.IGNORECASE,
)


def _has_frm_view(html: str) -> bool:
    return bool(
        re.search(r'<form[^>]+(?:name|id)=[\s"\']frmView', html, re.I)
    )


def _is_drmro_login_from_page(html: str) -> bool:
    m = re.search(r'property="og:url"\s+content="([^"]+)"', html, re.I)
    if m and "member/login" in m.group(1):
        return True
    if _has_frm_view(html):
        return False
    if 'id="formLogin"' in html and 'id="loginId"' in html:
        return True
    return False


def fetch_goods_view_html(
    goods_no: str, cookie: str | None, session: requests.Session | None = None
) -> str:
    from config import DRMRO_BASE

    g = (goods_no or "").strip()
    if not g.isdigit():
        return ""
    url = f"{DRMRO_BASE}/goods/goods_view.php?goodsNo={g}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    ck = _ascii_cookie(cookie)
    if ck:
        headers["Cookie"] = ck
    sess = session or requests.Session()
    r = sess.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    return decode_html(r)


def drmro_detail_is_orderable(html: str) -> tuple[bool | None, str]:
    """
    True: 주문(장바구니) 가능으로 보임. False: 품절/판매불가.
    None: 로그인 필요·파싱 불가(신뢰할 수 없음).
    """
    if not (html and len(html) > 500):
        return None, "empty_html"
    if _is_drmro_login_from_page(html):
        return None, "login_page"

    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select(
        "strong.item_soldout_bg, .item_soldout_bg, .item_soldout, .text_soldout"
    ):
        tx = (el.get_text() or "") + " ".join(el.get("class") or [])
        if re.search(r"SOLD|품절|일시", tx, re.I):
            if el.find_parent("form", {"name": "formLogin"}):
                continue
            return False, "dom_soldout_marker"

    sold_flags = [m.group(1).lower() for m in _RE_SOLDOUT_FL.finditer(html)]
    if "y" in sold_flags:
        return False, "soldOutFl_y"

    for node in soup.select(
        "a.btn_add_cart_, a.btn_add_cart, button.btn_add_cart_, [class*='btn_add_cart']"
    ):
        classes = " ".join(node.get("class") or "").lower()
        if "soldout" in classes or "btn_soldout" in classes:
            continue
        if "btn_add_cart" in classes or "add_cart" in classes:
            return True, "add_cart_button"

    for node in soup.select("a, button"):
        classes = " ".join(node.get("class") or []).lower()
        if "btn_soldout" in classes:
            return False, "soldout_button"
        if ("soldout" in classes) and ("cart" in classes or "order" in classes):
            return False, "soldout_order_button"

    if sold_flags and all(x == "n" for x in sold_flags):
        if re.search(
            r"(?:orderPossible|stockCnt|totalStock|goodsStock)[^:]{0,24}:\s*['\"]?0",
            html,
            re.I,
        ):
            return False, "js_stock_zero"
        return True, "soldOutFl_n"

    if re.search(r"btn_add_cart", html, re.I) and not re.search(
        r"btn_add_cart[^\n]{0,240}soldout", html, re.I
    ):
        return True, "heuristic_add_cart"

    return None, "uncertain"


def verify_drmro_items_with_detail(
    items: list[dict[str, Any]],
    cookie: str | None,
) -> list[dict[str, Any]]:
    """
    goods_view 로 각 goodsNo 재확인. 품절·로그인·불확실 시 목록에서 제외.
    """
    from config import DRMRO_DETAIL_DELAY_SEC, DRMRO_VERIFY_DETAIL

    if not items:
        return []
    if not DRMRO_VERIFY_DETAIL:
        return [
            {**it, "detailOk": True, "detailReason": "verify_skipped"}
            for it in items
        ]
    out: list[dict[str, Any]] = []
    any_login = False
    sess = requests.Session()
    for i, it in enumerate(items):
        gn = (it.get("goodsNo") or "").strip()
        if not gn:
            continue
        if i and DRMRO_DETAIL_DELAY_SEC > 0:
            time.sleep(DRMRO_DETAIL_DELAY_SEC)
        try:
            h = fetch_goods_view_html(gn, cookie, session=sess)
        except requests.RequestException:
            continue
        ok, reason = drmro_detail_is_orderable(h)
        if ok is None and reason == "login_page":
            any_login = True
        if ok is True:
            out.append(
                {**it, "detailOk": True, "detailReason": reason}
            )
    if not out and items and any_login:
        print(
            "[drmro] 상세(goods_view)가 로그인 화면입니다. "
            "DRMRO_ID+DRMRO_PW 또는 DRMRO_COOKIE로 회원 세션이 필요합니다.",
            file=sys.stderr,
        )
    return out
