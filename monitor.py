import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.example.json"
DEFAULT_STATE = ROOT / "state.json"

SEARCH_ENDPOINT = "https://www.samsungfund.com/search/samsungKodex/search_json.jsp"
TELEGRAM_ENDPOINT = "https://api.telegram.org/bot{token}/sendMessage"

POST_COLLECTIONS = {
    "k_notice": "공지사항",
    "marketreport": "시장전망",
    "kodexnews": "ETF 투자정보",
    "kodexreport": "ETF 리포트",
    "kodextv": "Kodex TV",
    "k_faq": "자주 묻는 질문",
    "k_investmentguidebook": "ETF 투자기초가이드",
    "k_other": "기타",
}


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def clean_title(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def absolute_url(url):
    if not url:
        return "https://www.samsungfund.com/etf/search.do"
    return urllib.parse.urljoin("https://www.samsungfund.com", url)


def fetch_search(query, retries=3):
    data = urllib.parse.urlencode({"collection": "ALL", "query": query}).encode("utf-8")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://www.samsungfund.com/etf/search.do",
    }
    req = urllib.request.Request(SEARCH_ENDPOINT, data=data, headers=headers)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read().decode("utf-8", "replace").lstrip()
            return json.loads(body)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"검색 API 호출 실패: {last_error}")


def item_url(collection, item):
    seq = item.get("DOCID") or item.get("SEQN") or item.get("F_ID") or ""
    if collection == "k_notice":
        return f"https://www.samsungfund.com/etf/lounge/notice-view.do?no={seq}"
    if collection in {"marketreport", "kodexreport", "kodexnews", "kodextv"}:
        direct = item.get("CNNT_URL") or item.get("URL")
        return absolute_url(direct) if direct else f"https://www.samsungfund.com/etf/lounge/newsroom-view.do?no={seq}"
    if collection == "k_faq":
        title = clean_title(item.get("TITLE"))
        return "https://www.samsungfund.com/etf/lounge/faq.do?searchText=" + urllib.parse.quote(title)
    return "https://www.samsungfund.com/etf/search.do?searchText=" + urllib.parse.quote(item.get("QUERY", ""))


def normalize_items(query, response):
    rows = []
    for result in response.get("RESULT", []):
        collection = result.get("COLLECTION")
        if collection not in POST_COLLECTIONS:
            continue
        for item in result.get("DATA") or []:
            doc_id = item.get("DOCID") or item.get("SEQN") or item.get("F_ID")
            title = clean_title(item.get("TITLE") or item.get("SUBJECT") or item.get("NAME"))
            if not doc_id or not title:
                continue
            rows.append(
                {
                    "id": f"{collection}:{doc_id}",
                    "query": query,
                    "collection": collection,
                    "category": POST_COLLECTIONS[collection],
                    "title": title,
                    "date": item.get("OPEN_DATE_YMD") or item.get("REG_DATE") or "",
                    "url": item_url(collection, item),
                }
            )
    return rows


def send_telegram(token, chat_id, text, dry_run=False):
    if dry_run:
        print(text)
        return
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TELEGRAM_ENDPOINT.format(token=token),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", "replace")
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {body}")


def build_message(item):
    parts = [
        "[Kodex 새 검색 결과]",
        f"검색어: {item['query']}",
        f"분류: {item['category']}",
        f"제목: {item['title']}",
    ]
    if item.get("date"):
        parts.append(f"게시일: {item['date']}")
    parts.append(f"링크: {item['url']}")
    return "\n".join(parts)


def kst_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))


def should_send_status(state, first_run, now):
    status = state.setdefault("status_notifications", {})
    if not status.get("first_run_sent"):
        status["first_run_sent"] = True
        return True, "첫 실행"

    if now.hour not in {9, 18}:
        return False, ""

    slot = f"{now:%Y-%m-%d}-{now.hour:02d}"
    if status.get("last_slot") == slot:
        return False, ""

    status["last_slot"] = slot
    label = "오전 9시" if now.hour == 9 else "오후 6시"
    return True, label


def build_status_message(searches, reason, now):
    watched = ", ".join(search["query"] for search in searches)
    return "\n".join(
        [
            "[Kodex 감시 상태]",
            "정상 감시 중입니다.",
            f"상태 알림: {reason}",
            f"확인 시간: {now:%Y-%m-%d %H:%M} KST",
            f"감시 대상: {watched}",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="Kodex 검색 결과를 감시하고 새 게시글을 텔레그램으로 알립니다.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="설정 JSON 경로")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="상태 JSON 경로")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만 합니다.")
    parser.add_argument("--notify-existing", action="store_true", help="첫 실행 기준선 저장 없이 기존 항목도 알립니다.")
    parser.add_argument("--no-last-checked", action="store_true", help="last_checked_at 값을 갱신하지 않습니다.")
    parser.add_argument("--status-notifications", action="store_true", help="첫 실행, 09시, 18시에 감시 상태 알림을 보냅니다.")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_json(config_path, {})
    searches = config.get("searches") or []
    if not searches:
        raise SystemExit(f"검색 설정이 없습니다: {config_path}")

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("telegram_bot_token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or config.get("telegram_chat_id")
    if not args.dry_run and (not token or not chat_id):
        raise SystemExit("TELEGRAM_BOT_TOKEN 및 TELEGRAM_CHAT_ID 환경변수 또는 config 값이 필요합니다.")

    state_path = Path(args.state)
    state = load_json(state_path, {"seen": {}})
    seen = state.setdefault("seen", {})
    first_run = not state_path.exists()
    new_items = []

    for search in searches:
        query = search["query"]
        response = fetch_search(query)
        current_items = normalize_items(query, response)
        key = search.get("name") or query
        previous = set(seen.get(key, []))
        current_ids = {item["id"] for item in current_items}
        if first_run and not args.notify_existing:
            seen[key] = sorted(current_ids)
            continue
        for item in current_items:
            if item["id"] not in previous:
                new_items.append(item)
        seen[key] = sorted(previous | current_ids)

    if not args.no_last_checked:
        state["last_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_json(state_path, state)

    for item in sorted(new_items, key=lambda x: (x.get("date") or "", x["id"])):
        send_telegram(token, chat_id, build_message(item), dry_run=args.dry_run)

    if args.status_notifications:
        now = kst_now()
        send_status, reason = should_send_status(state, first_run, now)
        if send_status:
            send_telegram(token, chat_id, build_status_message(searches, reason, now), dry_run=args.dry_run)
            save_json(state_path, state)

    print(f"확인 완료: 새 항목 {len(new_items)}건")


if __name__ == "__main__":
    main()
