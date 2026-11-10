"""zetpl 상품 입고 감시 → ntfy 푸시 알림.

사용법:
    python watch.py                # config.json 의 상품들을 계속 감시
    python watch.py --once         # 한 번만 확인하고 결과 출력
    python watch.py --test-push    # 휴대폰 알림 테스트

페이지에 박혀 있는 상품 JSON(totalStockQuantity, isSoldOut)을 읽어서
품절 → 입고로 바뀌는 순간 알림을 보낸다. 외부 패키지 없음.
"""
import json
import random
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os

if (HERE / "config.json").exists():
    CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
else:  # 클라우드(GitHub Actions): 환경변수로 설정
    CONFIG = {
        "ntfy_topic": os.environ["NTFY_TOPIC"],
        "urls": os.environ["WATCH_URLS"].split(),
        "interval_sec": int(os.environ.get("INTERVAL_SEC", "30")),
    }
CLOUD = bool(os.environ.get("GITHUB_ACTIONS"))
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME_SEC", "0"))  # 0 = 무제한
LOG = HERE / "watch.log"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def log(msg: str) -> None:
    line = f"{datetime.now():%m-%d %H:%M:%S} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except Exception:
        pass


def push(title: str, message: str, click: str | None = None, priority: int = 3, tags=None) -> None:
    body = {"topic": CONFIG["ntfy_topic"], "title": title, "message": message, "priority": priority}
    if click:
        body["click"] = click
    if tags:
        body["tags"] = tags
    req = urllib.request.Request(
        CONFIG.get("ntfy_server", "https://ntfy.sh").rstrip("/") + "/",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


def check(url: str) -> dict:
    pid = url.rstrip("/").split("/")[-1]
    req = urllib.request.Request(f"{url}?_={int(time.time())}", headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    # Next.js 페이지 안에 이스케이프된 JSON으로 들어 있음: \"id\":899,\"name\":\"...\",...,\"totalStockQuantity\":0,\"isSoldOut\":true
    m = re.search(
        r'\\"id\\":' + re.escape(pid) + r',\\"name\\":\\"(.*?)\\".*?\\"totalStockQuantity\\":(\d+),\\"isSoldOut\\":(true|false)',
        html,
    )
    if not m:
        raise ValueError("페이지에서 재고 정보를 못 찾음 (사이트 구조 변경?)")
    return {"name": m.group(1), "qty": int(m.group(2)), "soldout": m.group(3) == "true"}


def main() -> None:
    args = sys.argv[1:]
    urls = CONFIG["urls"]

    if "--test-push" in args:
        push("입고 알림 테스트", "이 알림이 보이면 설정 완료입니다.", click=urls[0], tags=["white_check_mark"])
        print("테스트 알림 보냄")
        return

    if "--once" in args:
        for u in urls:
            print(u, check(u))
        return

    interval = CONFIG.get("interval_sec", 30)
    state: dict[str, bool] = {}
    fails = 0
    fail_alerted = False
    log(f"감시 시작: {len(urls)}개, {interval}초 간격")
    push("입고 감시 시작", "\n".join(urls), tags=["eyes"], priority=2)

    while True:
        for u in urls:
            try:
                r = check(u)
                fails = 0
                if fail_alerted:
                    push("입고 감시 복구", "다시 정상적으로 확인 중입니다.", priority=2)
                    fail_alerted = False
                in_stock = (not r["soldout"]) or r["qty"] > 0
                prev = state.get(u)
                if prev is None:
                    log(f"{r['name']}: {'재고 ' + str(r['qty']) if in_stock else '품절'}")
                    if in_stock and CLOUD:  # 재시작 틈에 입고됐을 수 있으니 놓치지 않게 알림
                        push(f"재고 있음: {r['name']}", f"수량 {r['qty']}개", click=u, priority=5, tags=["rotating_light"])
                elif in_stock and not prev:
                    log(f"입고! {r['name']} 수량 {r['qty']}")
                    push(
                        f"입고! {r['name']}",
                        f"수량 {r['qty']}개 — 눌러서 바로 열기",
                        click=u,
                        priority=5,
                        tags=["rotating_light"],
                    )
                elif prev and not in_stock:
                    log(f"다시 품절: {r['name']}")
                    push(f"다시 품절: {r['name']}", u, click=u, priority=3)
                state[u] = in_stock
            except Exception as e:
                fails += 1
                log(f"확인 실패 ({fails}회 연속): {e}")
                if fails >= 10 and not fail_alerted:
                    try:
                        push("입고 감시 오류", f"10회 연속 확인 실패: {e}", priority=4, tags=["warning"])
                        fail_alerted = True
                    except Exception:
                        pass
        time.sleep(interval + random.uniform(-5, 5))


if __name__ == "__main__":
    main()
