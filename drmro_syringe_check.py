"""
drmro.com: 로그인(선택) 후 일회용주사기 검색 → 품절 제외 → 2·3·5ml(cc) + 23G + 1Inch 만 표시.
.env: DRMRO_ID, DRMRO_PW 또는 DRMRO_COOKIE
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import config  # noqa: F401
from config import DRMRO_COOKIE, DRMRO_ID, DRMRO_PW
from drmro_login import login_cookie_header
from drmro_search import (
    filter_orderable_and_spec,
    parse_goods_list,
    search_get,
    verify_drmro_items_with_detail,
)

# cc/ml 혼용 검색 (사이트는 규격에 주로 ml 표기)
_DEFAULT_QUERIES = (
    "일회용주사기 2cc 23G 1inch",
    "일회용주사기 3cc 23G 1inch",
    "일회용주사기 5cc 23G 1inch",
)


def _obtain_cookie(*, skip_playwright: bool) -> str | None:
    if not skip_playwright and DRMRO_ID and DRMRO_PW:
        ck = login_cookie_header()
        if ck:
            return ck
    if DRMRO_COOKIE:
        return DRMRO_COOKIE
    return None


def _dedupe_key(it: dict) -> str:
    return (it.get("goodsNo") or it.get("productCode") or it.get("url") or "")


def run(
    queries: tuple[str, ...] | list[str] | None, *, skip_playwright: bool
) -> dict:
    qlist = list(queries) if queries else list(_DEFAULT_QUERIES)
    ck = _obtain_cookie(skip_playwright=skip_playwright)
    if not ck and not skip_playwright and (DRMRO_ID and DRMRO_PW):
        return {
            "error": "no_cookie",
            "message": "로그인 실패. .env의 DRMRO_ID/DRMRO_PW 또는 DRMRO_COOKIE를 확인하세요.",
        }

    all_raw: list[dict] = []
    for kw in qlist:
        html = search_get(kw, ck)
        all_raw.extend(parse_goods_list(html))

    seen: set[str] = set()
    unique: list[dict] = []
    for it in all_raw:
        k = _dedupe_key(it)
        if not k or k in seen:
            continue
        seen.add(k)
        unique.append(it)

    matched_pre = filter_orderable_and_spec(unique, exclude_soldout=True)
    matched = verify_drmro_items_with_detail(matched_pre, ck)
    by_vol: dict[int, list[dict]] = defaultdict(list)
    for it in matched:
        v = it.get("volumeMl")
        if isinstance(v, int):
            by_vol[v].append(it)
    return {
        "queries": qlist,
        "totalParsed": len(unique),
        "orderableSpec235": len(matched_pre),
        "orderableAfterDetail": len(matched),
        "byVolume": {str(k): v for k, v in sorted(by_vol.items())},
        "items": matched,
    }


def main() -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="drmro 일회용주사기 2/3/5cc 23G 1Inch (품절 제외)")
    p.add_argument(
        "--no-login",
        action="store_true",
        help="로그인 생략(공개 검색만, DRMRO_COOKIE 있으면 전달)",
    )
    p.add_argument(
        "-q",
        "--query",
        action="append",
        dest="queries",
        help="검색어(여러 번 지정 가능). 기본: 2/3/5cc 각각 한 번씩",
    )
    p.add_argument("--json", action="store_true", help="JSON만 stdout")
    args = p.parse_args()
    qs = tuple(args.queries) if args.queries else None
    out = run(qs, skip_playwright=bool(args.no_login))
    if out.get("error") == "no_cookie":
        print(out.get("message", "no cookie"), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print("=== drmro — 품절 제외, 2·3·5ml/cc + 23G + 1Inch ===", file=sys.stderr)
    print(
        f"검색어: {', '.join(out.get('queries') or [])} | 파싱 {out.get('totalParsed')}건 "
        f"→ 리스트조건 {out.get('orderableSpec235')}건 → 상세확인 후 {out.get('orderableAfterDetail', 0)}건",
        file=sys.stderr,
    )
    for it in out.get("items") or []:
        vol = it.get("volumeMl")
        line = (
            f"[{vol}ml] {it.get('title', '')} | {it.get('spec', '')} | "
            f"{it.get('price', '')} | {it.get('url', '')}"
        )
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
