"""Eastmoney whole-market breadth snapshot collector.

The popularity/race feed intentionally contains only a small hot-stock sample.
This adapter uses Eastmoney's A-share quote list so market-effect statistics are
calculated from the broad market rather than from the top-30 popularity rows.
"""

from datetime import datetime
import json
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import load_config


URL = "https://push2.eastmoney.com/api/qt/clist/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HeatFlow/0.7",
    "Referer": "https://quote.eastmoney.com/",
}
CURL_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _fetch_page(params, timeout):
    request_url = URL + "?" + urlencode(params)
    request = Request(request_url, headers=HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        process = subprocess.run(["curl.exe", "--http1.1", "-sS", "-L", "--max-time", str(timeout), "-A", HEADERS["User-Agent"], "-H", "Referer: https://quote.eastmoney.com/", request_url], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=CURL_FLAGS)
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Eastmoney whole-market breadth request failed") from exc


def fetch_market_breadth(now=None):
    """Return one whole-market breadth snapshot for the current trading date."""
    now = now or datetime.now()
    cfg = load_config().get("collector", {})
    params = {
        "pn": 1,
        # The endpoint can silently cap a very large page.  Use a moderate
        # page and follow its reported total so the result is genuinely 全A.
        "pz": min(1000, max(100, int(cfg.get("market_breadth_page_size", 1000)))),
        "po": 1,
        "np": 1,
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        # Shanghai/Shenzhen A-share boards; exclude funds, indices and bonds.
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f12,f14",
    }
    timeout = int(cfg.get("timeout_seconds", 12))
    payload = _fetch_page(params, timeout)
    data = payload.get("data") or {}
    rows = data.get("diff") or []
    total = int(data.get("total") or len(rows))
    page_size = int(params["pz"])
    # Deduplicate by stock code because some board filters overlap.
    merged = {str(row.get("f12") or index): row for index, row in enumerate(rows)}
    for page in range(2, min((total + page_size - 1) // page_size, 12) + 1):
        page_params = {**params, "pn": page}
        page_rows = ((_fetch_page(page_params, timeout).get("data") or {}).get("diff") or [])
        if not page_rows:
            break
        for index, row in enumerate(page_rows):
            merged[str(row.get("f12") or f"{page}:{index}")] = row
    rows = list(merged.values())
    changes = []
    for row in rows:
        try:
            value = row.get("f3")
            if value is None or str(value) in {"-", "None", "null"}:
                continue
            changes.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(changes) < 100:
        raise RuntimeError(f"Eastmoney whole-market breadth returned only {len(changes)} rows")
    count = len(changes)
    up = sum(value > 0 for value in changes)
    down = sum(value < 0 for value in changes)
    flat = count - up - down
    return {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "sample_size": count,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "red_ratio": round(up / count * 100, 1),
        "avg_change": round(sum(changes) / count, 2),
        "strong_ratio": round(sum(value >= 5 for value in changes) / count * 100, 1),
        "weak_ratio": round(sum(value <= -5 for value in changes) / count * 100, 1),
        "source": "eastmoney_market_breadth",
    }
