"""
TheSHOP search + Telegram on an interval (default 10 min).
Env: same as Doctorville for TELEGRAM_*; SHOP_ID/SHOP_PW or SHOP_COOKIE; THE_SHOP_SEARCH_KEYWORD.
기본: 검색결과에 THE_SHOP_ALERT_PATTERNS(기본 3cc 23G, 5cc 23G)가 새로 뜬 경우에만 텔레그램(중복·동일 러닝은 상태 파일로 억제).
선택: THE_SHOP_TELEGRAM_FULL_LIST=1 이 매전체 목록을 추가로 전송.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time

from config import (
    ALERT_PATTERNS,
    CHECK_INTERVAL_MINUTES,
    SEARCH_KEYWORD,
    SHOP_ID,
    SHOP_PW,
    STATE_FILE,
    TELEGRAM_FULL_LIST,
)
from telegram_notify import chunk_telegram_text, send_message
from theshop_search import obtain_cookie, run_search


def _match_text_for_item(it: dict) -> str:
    return f"{(it.get('title') or '')} {(it.get('goodsCd') or '')}"


def _pattern_matches(hay: str, pattern: str) -> bool:
    p = (pattern or "").strip()
    if not p:
        return False
    parts = [x for x in re.split(r"\s+", p) if x]
    if not parts:
        return False
    rgx = r"\s*".join(re.escape(x) for x in parts)
    return re.search(rgx, hay, re.I) is not None


def _alert_key(item: dict, pat: str) -> str:
    g = (item.get("goodsCd") or "").strip()
    t = (item.get("title") or "")[:200]
    return f"{g}|{pat}|{t}"


def _collect_new_alerts(
    items: list[dict], last_keys: set[str]
) -> tuple[list[tuple[str, dict]], set[str]]:
    """(신규 (패턴, 상품) 목록, 이번 런에서 매칭된 전체 키) — 다음 런 비교용."""
    current: set[str] = set()
    new_events: list[tuple[str, dict]] = []
    for it in items:
        mt = _match_text_for_item(it)
        for pat in ALERT_PATTERNS:
            if not _pattern_matches(mt, pat):
                continue
            k = _alert_key(it, pat)
            current.add(k)
            if k not in last_keys:
                new_events.append((pat, it))
    return new_events, current


def _load_state_keys() -> set[str]:
    if not STATE_FILE.is_file():
        return set()
    try:
        raw = STATE_FILE.read_text(encoding="utf-8")
        d = json.loads(raw)
        return set(d.get("last_match_keys", []) or [])
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _save_state_keys(keys: set[str]) -> None:
    try:
        STATE_FILE.write_text(
            json.dumps(
                {"last_match_keys": sorted(keys)},
                ensure_ascii=False,
                indent=0,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _format_alert_message(keyword: str, events: list[tuple[str, dict]]) -> str:
    pat_line = ", ".join(ALERT_PATTERNS)
    lines: list[str] = [
        "[TheSHOP] 조건 충족(신규)",
        f"검색어: {keyword}",
        f"감시 키워드: {pat_line}",
        "",
    ]
    for pat, it in events:
        title = (it.get("title") or "").strip() or "(제목 없음)"
        lines.append(f"· [{pat}] {title}")
        u = (it.get("url") or "").strip()
        if u:
            lines.append(f"  {u}")
    return "\n".join(lines)


def _format_message(data: dict) -> str:
    lines = [
        "[TheSHOP] " + data.get("keyword", ""),
        "count: " + str(data.get("count", 0)),
        "",
    ]
    for i, it in enumerate(data.get("items") or [], 1):
        title = (it.get("title") or "").strip() or "(no title)"
        url = (it.get("url") or "").strip()
        gc = (it.get("goodsCd") or "").strip()
        pr = (it.get("price") or "").strip()
        line = f"{i}. {title}"
        if pr:
            line += f"  |  {pr}"
        lines.append(line)
        if gc:
            lines.append(f"   code: {gc}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _print_run_list(keyword: str, data: dict) -> None:
    n = int(data.get("count") or 0)
    print(
        f"[{_ts()}] TheSHOP | 검색어: {keyword!r} | 상품 {n}건",
        file=sys.stderr,
    )
    for i, it in enumerate(data.get("items") or [], 1):
        title = (it.get("title") or "").strip() or "(제목없음)"
        pr = (it.get("price") or "").strip()
        gc = (it.get("goodsCd") or "").strip()
        extra = []
        if pr:
            extra.append(pr)
        if gc:
            extra.append(f"#{gc}")
        suf = f"  |  {'  '.join(extra)}" if extra else ""
        print(f"  {i:2d}. {title}{suf}", file=sys.stderr)


def _print_run_error(
    keyword: str, err: str, data: dict | None, *, verbose: bool
) -> None:
    err_msg = err
    if err == "parse_failed":
        err_msg = (
            "parse_failed (리스트 파싱 실패). "
            "THE_SHOP_DEBUG_HTML=1 로 last_search.html 저장 후 확인"
        )
    print(
        f"[{_ts()}] TheSHOP | 검색어: {keyword!r} | {err_msg}",
        file=sys.stderr,
    )
    if verbose and data is not None:
        print(
            json.dumps(data, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )


def run_once(keyword: str, *, verbose: bool = False) -> int:
    ck = obtain_cookie()
    if not ck:
        print(
            f"[{_ts()}] TheSHOP | 로그인 없음. .env에 SHOP_ID+SHOP_PW 또는 SHOP_COOKIE 필요.",
            file=sys.stderr,
        )
        return 1
    data = run_search(keyword, ck)
    if data.get("error") == "login_required" and SHOP_ID and SHOP_PW:
        from theshop_login import login_cookie_header

        print(
            f"[{_ts()}] TheSHOP | 세션 만료, Playwright로 재로그인…",
            file=sys.stderr,
        )
        ck = login_cookie_header()
        if ck:
            data = run_search(keyword, ck)
    if data.get("error"):
        err = data.get("error")
        _print_run_error(keyword, str(err), data, verbose=verbose)
        if err == "login_required":
            return 1
        if err == "http_failed":
            return 3
        return 2
    _print_run_list(keyword, data)
    if verbose:
        print(
            json.dumps(data, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
    last_keys = _load_state_keys()
    items = data.get("items") or []
    new_alerts, current_keys = _collect_new_alerts(items, last_keys)
    _save_state_keys(current_keys)
    if new_alerts:
        alert_txt = _format_alert_message((data.get("keyword") or keyword), new_alerts)
        if send_message(alert_txt):
            print(
                f"[{_ts()}] TheSHOP | 텔레그램: 감시 키워드 알림 전송",
                file=sys.stderr,
            )
        else:
            print(
                f"[{_ts()}] TheSHOP | 텔레그램 전송 실패(토큰/CHAT_ID 확인)",
                file=sys.stderr,
            )
    if TELEGRAM_FULL_LIST:
        if send_message(_format_message(data)):
            print(
                f"[{_ts()}] TheSHOP | 텔레그램: 전체 목록 전송( THE_SHOP_TELEGRAM_FULL_LIST )",
                file=sys.stderr,
            )
    return 0


def run_loop(keyword: str, *, verbose: bool) -> None:
    while True:
        try:
            run_once(keyword, verbose=verbose)
        except KeyboardInterrupt:
            print(f"[{_ts()}] TheSHOP | 종료(Ctrl+C)", file=sys.stderr)
            raise SystemExit(0)
        except Exception as e:
            print(f"[{_ts()}] TheSHOP | 오류: {e}", file=sys.stderr)
            try:
                for part in chunk_telegram_text(f"[TheSHOP] error: {e}"):
                    send_message(part)
            except Exception:
                pass
        m = max(1, CHECK_INTERVAL_MINUTES)
        next_ts = (datetime.datetime.now() + datetime.timedelta(minutes=m)).strftime(
            "%H:%M"
        )
        print(
            f"[{_ts()}] TheSHOP | {m}분 후 재검색(대략 {next_ts}…)",
            file=sys.stderr,
        )
        time.sleep(m * 60)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="single run then exit")
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="JSON(진단) 추가 출력, 오류 시 html_sample 등",
    )
    p.add_argument("keyword", nargs="?", default=SEARCH_KEYWORD, help="search keyword")
    args = p.parse_args()
    kw = (args.keyword or SEARCH_KEYWORD).strip()
    v = bool(args.verbose)
    if args.once:
        return run_once(kw, verbose=v)
    run_loop(kw, verbose=v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
