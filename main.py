"""
TheSHOP → drmro 순서.
- 규격: 2/3/5cc·23G·1", 품절/상세(drmro) 제외. 기본: 한 쪽(drmro만) 있어도 [추가/최초] 알림. **둘 다** 필요 시 STOCK_NOTIFY_REQUIRE_BOTH_SITES=true
- 텔레그램: **스냅샷이 변할 때만** (동일이면 10분마다 반복 전송 없음). THE_SHOP_CHECK_INTERVAL_MINUTES=10 기본.
- THE_SHOP_TELEGRAM_FULL_LIST: ‘변화’를 보낼 때 TheSHOP 극격 요약을 같은 메시지에 붙일 뿐, 매 루프마다 별도로 보내지 않음.
Env: TELEGRAM_*, SHOP_*, THE_SHOP_SEARCH_KEYWORD, DRMRO_*
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time

from config import (
    CHECK_INTERVAL_MINUTES,
    DRMRO_ID,
    DRMRO_PW,
    SEARCH_KEYWORD,
    SHOP_ID,
    SHOP_PW,
    STOCK_NOTIFY_REQUIRE_BOTH_SITES,
    STOCK_NOTIFY_STATE_FILE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FULL_LIST,
)
from drmro_search import filter_theshop_syringe_23g1_235cc
from drmro_syringe_check import run as drmro_syringe_run
from telegram_notify import chunk_telegram_text, send_message
from theshop_search import obtain_cookie, run_search


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _orderable_notify_key(item: dict) -> str:
    s = (item.get("source") or "").strip()
    if s == "theshop":
        return f"ts|{item.get('goodsCd', '')}|{item.get('volumeMl')}"
    if s == "drmro":
        return f"dr|{item.get('goodsNo', '')}|{item.get('volumeMl')}"
    return f"x|{item.get('url', '')}|{item.get('volumeMl')}"


def _load_orderable_state() -> tuple[set[str], dict[str, dict]]:
    """이전 러닝 키 집합 + 표시용 메타(빠짐 항목 안내)."""
    if not STOCK_NOTIFY_STATE_FILE.is_file():
        return set(), {}
    try:
        raw = STOCK_NOTIFY_STATE_FILE.read_text(encoding="utf-8")
        d = json.loads(raw)
        keys = set(d.get("last_orderable_keys", []) or [])
        meta = d.get("key_meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        return keys, {str(k): v for k, v in meta.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError, TypeError):
        return set(), {}


def _build_key_meta(
    all_items: list[dict],
) -> tuple[set[str], dict[str, dict]]:
    keys: set[str] = set()
    meta: dict[str, dict] = {}
    for it in all_items:
        k = _orderable_notify_key(it)
        if not k or k in keys:
            continue
        keys.add(k)
        meta[k] = {
            "key": k,
            "source": (it.get("source") or "?")[:20],
            "title": ((it.get("title") or "")[:200]) or "(제목없음)",
            "url": ((it.get("url") or "")[:800]),
            "vol": it.get("volumeMl"),
        }
    return keys, meta


def _save_orderable_state(keys: set[str], key_meta: dict[str, dict]) -> None:
    try:
        STOCK_NOTIFY_STATE_FILE.write_text(
            json.dumps(
                {
                    "last_orderable_keys": sorted(keys),
                    "key_meta": {k: key_meta[k] for k in sorted(keys) if k in key_meta},
                },
                ensure_ascii=False,
                indent=0,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _format_telegram_theshop_spec_list(
    keyword: str, filtered: list[dict], total_search_count: int
) -> str:
    """2/3/5cc·23G·1Inch(품절문구제외)만."""
    n = len(filtered)
    lines: list[str] = [
        "[TheSHOP] 23G 1Inch · 2/3/5cc 규격만 (THE_SHOP_TELEGRAM_FULL_LIST)",
        f"검색어: {keyword}",
        f"검색 전체 {total_search_count}건 → 규격 {n}건",
        "",
    ]
    for i, it in enumerate(filtered, 1):
        vol = it.get("volumeMl", "?")
        title = (it.get("title") or "").strip() or "(no title)"
        url = (it.get("url") or "").strip()
        gc = (it.get("goodsCd") or "").strip()
        pr = (it.get("price") or "").strip()
        line = f"{i}. [{vol}ml] {title}"
        if pr:
            line += f"  |  {pr}"
        lines.append(line)
        if gc:
            lines.append(f"   code: {gc}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


def _format_item_block_lines(
    it: dict, *, show_detail_reason: bool = True
) -> list[str]:
    vol = it.get("volumeMl", "?")
    title = (it.get("title") or "").strip() or "(제목없음)"
    spec = (it.get("spec") or "").strip()
    pr = (it.get("price") or "").strip()
    gc = (it.get("goodsCd") or it.get("productCode") or "").strip()
    u = (it.get("url") or "").strip()
    dr = (it.get("detailReason") or "").strip()
    one = f"· [{vol}ml] {title}"
    if spec:
        one += f" / {spec}"
    if pr:
        one += f" / {pr}"
    if gc:
        one += f" / #{gc}"
    if show_detail_reason and dr and it.get("source") == "drmro":
        one += f" ({dr})"
    out = [one]
    if u:
        out.append(f"  {u}")
    return out


def _format_telegram_change(
    theshop_keyword: str,
    *,
    is_initial: bool,
    added: list[dict],
    removed_keys: set[str],
    last_meta: dict[str, dict],
) -> str:
    lines: list[str] = [
        (
            "[주사기] 23G 1Inch · 2/3/5cc — 최초 스냅샷(주문가능)"
            if is_initial
            else "[주사기] 23G 1Inch · 2/3/5cc — 모니터링 변화"
        ),
        f"TheSHOP 검색어: {theshop_keyword}",
        f"+추가 {len(added)}건, -빠짐 {len(removed_keys)}건"
        if not is_initial
        else f"주문가능 {len(added)}건 (이후부터는 이 목록이 바뀔 때만 알림)",
        "",
    ]
    if added:
        by: dict[str, list[dict]] = {"theshop": [], "drmro": [], "other": []}
        for it in added:
            s = (it.get("source") or "?").lower()
            if s in by:
                by[s].append(it)
            else:
                by["other"].append(it)
        for label, key in (("TheSHOP", "theshop"), ("drmro", "drmro"), ("기타", "other")):
            ch = by.get(key) or []
            if not ch:
                continue
            lines.append(f"— {label} · 추가 —")
            for it in ch:
                lines.extend(_format_item_block_lines(it))
            lines.append("")

    if removed_keys and not is_initial:
        lines.append("— 빠짐(이전 러닝엔 있었음) —")
        for rk in sorted(removed_keys):
            m = last_meta.get(rk) or {}
            t = m.get("title") or ""
            u = m.get("url") or ""
            src = m.get("source") or "?"
            line = t if t else f"(키) {rk}"
            lines.append(f"· ({src}) {line}")
            if u:
                lines.append(f"  {u}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _dedupe_by_notify_key(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        k = _orderable_notify_key(it)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _print_theshop_list(
    keyword: str, data: dict, *, theshop_spec: list[dict]
) -> None:
    n = int(data.get("count") or 0)
    print(
        f"\n[ {_ts()} ] ========== TheSHOP (전체) ========== 검색어: {keyword!r}  상품 {n}건",
        file=sys.stderr,
    )
    for i, it in enumerate(data.get("items") or [], 1):
        title = (it.get("title") or "").strip() or "(제목없음)"
        pr = (it.get("price") or "").strip()
        gc = (it.get("goodsCd") or "").strip()
        extra = [x for x in (pr, f"#{gc}" if gc else "") if x]
        suf = f"  |  {'  '.join(extra)}" if extra else ""
        print(f"  {i:2d}. {title}{suf}", file=sys.stderr)
    print(
        f"  → 규격필터(23G 1Inch·2/3/5cc, 품절문구제외): {len(theshop_spec)}건",
        file=sys.stderr,
    )


def _print_drmro_list(drm: dict) -> None:
    print(
        f"\n[ {_ts()} ] ========== drmro (23G 1Inch · 2/3/5cc, 품절제외) ==========",
        file=sys.stderr,
    )
    if drm.get("error"):
        print(f"  오류: {drm.get('message', drm.get('error'))}", file=sys.stderr)
        return
    qs = drm.get("queries") or []
    print(
        f"  검색: {', '.join(qs) if qs else '(기본)'}  "
        f"| 파싱 {drm.get('totalParsed', 0)}건 → 리스트조건 {drm.get('orderableSpec235', 0)}건 "
        f"→ 상세확인 후 {drm.get('orderableAfterDetail', 0)}건",
        file=sys.stderr,
    )
    for it in drm.get("items") or []:
        vol = it.get("volumeMl")
        line = (
            f"  [{vol}ml] {it.get('title', '')} | {it.get('spec', '')} | "
            f"{it.get('price', '')} | {it.get('url', '')}"
        )
        print(line, file=sys.stderr)


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
        print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)


def run_combined_once(
    theshop_keyword: str,
    *,
    verbose: bool = False,
    skip_drmro_login: bool = False,
    force_send: bool = False,
) -> int:
    if sys.platform == "win32" and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # -------- TheSHOP --------
    ck = obtain_cookie()
    if not ck:
        print(
            f"[{_ts()}] TheSHOP | 로그인 없음. .env: SHOP_ID+SHOP_PW 또는 SHOP_COOKIE",
            file=sys.stderr,
        )
        return 1
    data = run_search(theshop_keyword, ck)
    if data.get("error") == "login_required" and SHOP_ID and SHOP_PW:
        from theshop_login import login_cookie_header

        print(f"[{_ts()}] TheSHOP | 세션 만료, 재로그인…", file=sys.stderr)
        ck = login_cookie_header()
        if ck:
            data = run_search(theshop_keyword, ck)
    if data.get("error"):
        err = str(data.get("error"))
        _print_run_error(theshop_keyword, err, data, verbose=verbose)
        if err == "login_required":
            return 1
        if err == "http_failed":
            return 3
        return 2
    theshop_orderable = filter_theshop_syringe_23g1_235cc(
        data.get("items") or []
    )
    _print_theshop_list(theshop_keyword, data, theshop_spec=theshop_orderable)
    if verbose:
        print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)

    # -------- drmro --------
    drm_skip = skip_drmro_login or (not DRMRO_ID and not DRMRO_PW)
    drm = drmro_syringe_run(None, skip_playwright=drm_skip)
    _print_drmro_list(drm)
    if drm.get("error"):
        print(
            f"[{_ts()}] drmro | {drm.get('message', '오류')}",
            file=sys.stderr,
        )
    drmro_items: list[dict] = []
    for it in drm.get("items") or []:
        drmro_items.append({**it, "source": "drmro"})

    # -------- 주문가능 집합 변화(최초 / 추가·빠짐) → 텔레그램 --------
    last_keys, last_meta = _load_orderable_state()
    all_orderable: list[dict] = theshop_orderable + drmro_items
    current_keys, current_meta = _build_key_meta(all_orderable)
    added_keys = current_keys - last_keys
    removed_keys = last_keys - current_keys
    is_initial = (len(last_keys) == 0 and len(current_keys) > 0 and len(removed_keys) == 0)

    if force_send:
        n_ts, n_dr = len(theshop_orderable), len(drmro_items)
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print(
                f"[{_ts()}] --force-send: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 필요",
                file=sys.stderr,
            )
            return 1
        if not current_keys:
            print(
                f"[{_ts()}] --force-send: 전송할 주문가능(극격) 0건",
                file=sys.stderr,
            )
            return 0
        uniq = _dedupe_by_notify_key(all_orderable)
        pre = (
            "[TheSHOP+drmro] **강제** 현재 주문가능(스냅샷 변화와 무관 1회)\n"
            f"TheSHOP 검색어: {theshop_keyword}\n"
            f"theshop 극격 {n_ts}건 · drmro {n_dr}건 · 총 {len(uniq)}건\n\n"
        )
        body = pre + _format_telegram_change(
            theshop_keyword,
            is_initial=True,
            added=uniq,
            removed_keys=set(),
            last_meta={},
        )
        if TELEGRAM_FULL_LIST and theshop_orderable:
            body = body + "\n\n" + _format_telegram_theshop_spec_list(
                theshop_keyword,
                theshop_orderable,
                int(data.get("count") or 0),
            )
        parts = chunk_telegram_text(body)
        ok = True
        for part in parts:
            if not send_message(part):
                ok = False
                break
        if not ok:
            print(
                f"[{_ts()}] --force-send: 텔레그램 전송 실패",
                file=sys.stderr,
            )
            return 1
        _save_orderable_state(current_keys, current_meta)
        print(
            f"[{_ts()}] 텔레그램: **강제** 전송 완료(보통 `stock_notify_state` 와 같아도 1회 보냄)",
            file=sys.stderr,
        )
        return 0

    if not added_keys and not removed_keys:
        _save_orderable_state(current_keys, current_meta)
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print(
                f"[{_ts()}] [중요] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없으면 "
                f"알림이 **절대** 가지 않습니다. TheShop .env(또는 Doctorville .env)에 설정하세요.",
                file=sys.stderr,
            )
        if current_keys or last_keys:
            print(
                f"[{_ts()}] 텔레그램: 전송할 ‘변화’ 없음 — "
                f"stock_notify_state.json 스냅샷({len(current_keys)}건) = 이전 런과 동일. "
                f"같은 내용 1회만 다시: python main.py --once --force-send  또는  "
                f"상태 리셋: {STOCK_NOTIFY_STATE_FILE.resolve()} 삭제",
                file=sys.stderr,
            )
        else:
            print(
                f"[{_ts()}] 텔레그램: 주문가능(극격) 0건(스냅샷 비어 있음) — (다음: {max(1, CHECK_INTERVAL_MINUTES)}분)",
                file=sys.stderr,
            )
        return 0

    n_ts, n_dr = len(theshop_orderable), len(drmro_items)
    if STOCK_NOTIFY_REQUIRE_BOTH_SITES:
        if removed_keys:
            can_send = True
        else:
            can_send = n_ts >= 1 and n_dr >= 1
    else:
        can_send = True
    if not can_send:
        _save_orderable_state(current_keys, current_meta)
        print(
            f"[{_ts()}] 텔레그램: 전송 생략(추가/최초: TheSHOP·DRMRO **각 1건 이상**일 때만. "
            f"지금 theshop={n_ts} drmro={n_dr}건). 빠짐(품절)만 있을 때는 알림함.",
            file=sys.stderr,
        )
        return 0

    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print(
            f"[{_ts()}] 텔레그램: 토큰/CHAT_ID 없음. "
            f"이번 러닝 변화 +{len(added_keys)} -{len(removed_keys)} — 전송·상태갱신 생략(다음에 .env 설정 시 알림).",
            file=sys.stderr,
        )
        return 0

    seen_add: set[str] = set()
    added_items: list[dict] = []
    for it in all_orderable:
        k = _orderable_notify_key(it)
        if k in added_keys and k not in seen_add:
            seen_add.add(k)
            added_items.append(it)
    body = _format_telegram_change(
        theshop_keyword,
        is_initial=is_initial,
        added=added_items,
        removed_keys=removed_keys,
        last_meta=last_meta,
    )
    if TELEGRAM_FULL_LIST and theshop_orderable:
        body = body + "\n\n" + _format_telegram_theshop_spec_list(
            theshop_keyword,
            theshop_orderable,
            int(data.get("count") or 0),
        )
    parts = chunk_telegram_text(body)
    ok = True
    for part in parts:
        if not send_message(part):
            ok = False
            break
    if ok:
        _save_orderable_state(current_keys, current_meta)
        print(
            f"[{_ts()}] 텔레그램: 전송 완료 ("
            f"{'최초' if is_initial else '변화'} +{len(added_keys)} -{len(removed_keys)})",
            file=sys.stderr,
        )
    else:
        print(
            f"[{_ts()}] 텔레그램 전송 실패 — 상태 파일은 갱신하지 않음(다음 런에 재시도). "
            f"또는 [telegram] api 오류 위 로그 확인",
            file=sys.stderr,
        )
    return 0


def run_loop(
    keyword: str, *, verbose: bool, no_drmro_login: bool = False
) -> None:
    while True:
        try:
            run_combined_once(
                keyword,
                verbose=verbose,
                skip_drmro_login=no_drmro_login,
            )
        except KeyboardInterrupt:
            print(f"[{_ts()}] 종료(Ctrl+C)", file=sys.stderr)
            raise SystemExit(0)
        except Exception as e:
            print(f"[{_ts()}] 오류: {e}", file=sys.stderr)
            try:
                for part in chunk_telegram_text(f"[TheSHOP+drmro] error: {e}"):
                    send_message(part)
            except Exception:
                pass
        m = max(1, CHECK_INTERVAL_MINUTES)
        next_ts = (datetime.datetime.now() + datetime.timedelta(minutes=m)).strftime(
            "%H:%M"
        )
        print(
            f"[{_ts()}] {m}분 후 재검색 — 변화 있을 때만 텔레그램(대략 {next_ts})",
            file=sys.stderr,
        )
        time.sleep(m * 60)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="한 번 실행 후 종료")
    p.add_argument(
        "-v", "--verbose", action="store_true", help="TheSHOP JSON 등 진단"
    )
    p.add_argument(
        "--no-drmro-login",
        action="store_true",
        help="drmro Playwright 로그인 생략(쿠키만/공개 검색). DRMRO_ID+PW가 있으면 기본은 로그인",
    )
    p.add_argument(
        "keyword",
        nargs="?",
        default=SEARCH_KEYWORD,
        help="TheSHOP 검색어( drmro는 2/3/5cc 고정 검색 )",
    )
    p.add_argument(
        "--force-send",
        action="store_true",
        help="--once 전용. 스냅샷이 이전 런과 같아도 지금 주문가능(drmro+theshop) 목록 1회 텔레그램(토큰·채팅ID 필요)",
    )
    args = p.parse_args()
    kw = (args.keyword or SEARCH_KEYWORD).strip()
    if args.force_send and not args.once:
        print(
            "오류: --force-send 는 --once 와 같이 쓰세요. "
            "예: python main.py --once --force-send",
            file=sys.stderr,
        )
        return 2
    if args.once:
        return run_combined_once(
            kw,
            verbose=bool(args.verbose),
            skip_drmro_login=args.no_drmro_login,
            force_send=bool(args.force_send),
        )
    run_loop(
        kw,
        verbose=bool(args.verbose),
        no_drmro_login=args.no_drmro_login,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
