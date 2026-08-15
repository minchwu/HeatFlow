"""Public Tonghuashun A-share market table adapter."""

from html.parser import HTMLParser
import json
import re
import subprocess
from urllib.request import Request, urlopen

from ..config import load_config

CURL_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _float(value, default=0.0):
    text = re.sub(r"[^0-9+\-.]", "", str(value or ""))
    try: return float(text)
    except ValueError: return default


def _amount(value):
    text = str(value or "").strip(); number = _float(text)
    if "亿" in text: return number * 100000000
    if "万" in text: return number * 10000
    return number


def _board(code):
    if code.startswith("688"): return "科创板"
    if code.startswith("30"): return "创业板"
    if code.startswith(("4", "8", "92")): return "北交所"
    return "主板"


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_target = False; self.depth = 0; self.in_row = False; self.in_cell = False
        self.cell = []; self.row = []; self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "m-pager-table" in attrs.get("class", ""):
            self.in_target = True; self.depth = 1; return
        if self.in_target and tag == "table": self.depth += 1
        if not self.in_target: return
        if tag == "tr": self.in_row = True; self.row = []
        elif tag == "td" and self.in_row: self.in_cell = True; self.cell = []

    def handle_endtag(self, tag):
        if not self.in_target: return
        if tag == "td" and self.in_cell:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip()); self.in_cell = False
        elif tag == "tr" and self.in_row:
            if len(self.row) >= 10: self.rows.append(self.row)
            self.in_row = False
        elif tag == "table":
            self.depth -= 1
            if self.depth <= 0: self.in_target = False

    def handle_data(self, data):
        if self.in_cell: self.cell.append(data)


def collect_market():
    cfg = load_config().get("collector", {}); ths_cfg = cfg.get("ths", {})
    request = Request(ths_cfg.get("url", "https://q.10jqka.com.cn/"), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HeatFlow/0.6",
        "Referer": "https://q.10jqka.com.cn/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urlopen(request, timeout=int(cfg.get("timeout_seconds", 12))) as response:
        html = response.read().decode(response.headers.get_content_charset() or "gbk", errors="replace")
    parser = _TableParser(); parser.feed(html); output = []
    for cells in parser.rows:
        code = re.sub(r"\D", "", cells[1])[-6:]
        if len(code) != 6: continue
        output.append({
            "ths_rank": int(_float(cells[0], 999)), "code": code, "name": cells[2], "last_price": _float(cells[3]),
            "price_change": _float(cells[4]), "change_amount": _float(cells[5]), "change_speed": _float(cells[6]),
            "turnover": _float(cells[7]), "volume_ratio": _float(cells[8]), "amplitude": _float(cells[9]),
            "amount": _amount(cells[10]) if len(cells) > 10 else 0, "board": _board(code),
        })
    if len(output) < 10:
        raise RuntimeError(f"Tonghuashun returned only {len(output)} market rows")
    return output


def score_row(row):
    momentum = max(0, min(10, 5 + row.get("price_change", 0) / 4))
    turnover = max(0, min(10, row.get("turnover", 0) / 3))
    volume = max(0, min(10, row.get("volume_ratio", 0) * 2))
    amplitude = max(0, min(10, row.get("amplitude", 0) / 2))
    return round(0.40 * momentum + 0.25 * turnover + 0.20 * volume + 0.15 * amplitude, 2)


def fetch_history(code, limit=21):
    cfg = load_config().get("collector", {}); timeout = int(cfg.get("timeout_seconds", 12))
    url = f"https://d.10jqka.com.cn/v6/line/hs_{code}/01/last.js"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36", "Referer": f"http://stockpage.10jqka.com.cn/{code}/"}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response: text = response.read().decode("utf-8", errors="replace")
    except Exception:
        process = subprocess.run(["curl.exe", "--http1.1", "-sS", "-L", "--max-time", str(timeout), "-A", headers["User-Agent"], "-H", f"Referer: {headers['Referer']}", url], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=CURL_FLAGS)
        text = process.stdout
    match = re.search(r"\((\{.*\})\)\s*$", text, re.S)
    if not match: raise RuntimeError(f"Tonghuashun history unavailable for {code}")
    payload = json.loads(match.group(1)); raw_rows = [row.split(",") for row in str(payload.get("data", "")).split(";") if row]
    candles = []; previous_close = None
    for values in raw_rows:
        if len(values) < 8: continue
        open_price, high, low, close = (_float(values[i]) for i in range(1, 5))
        prior_close = previous_close
        pct = ((close / prior_close - 1) * 100) if prior_close else 0
        amplitude = ((high - low) / prior_close * 100) if prior_close else 0
        previous_close = close or previous_close
        date_raw = values[0]; date_text = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 and date_raw.isdigit() else date_raw
        candles.append({"date": date_text, "open": open_price, "close": close, "high": high, "low": low, "volume": _float(values[5]), "amount": _float(values[6]), "amplitude": round(amplitude, 2), "price_change": round(pct, 2), "change_amount": round(close - (prior_close or close), 2), "turnover": _float(values[7])})
    if not candles: raise RuntimeError(f"Tonghuashun history returned no rows for {code}")
    return {"code": code, "name": payload.get("name") or code, "candles": candles[-limit:], "provider": "ths_history"}
