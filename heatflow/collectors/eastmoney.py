"""Eastmoney popularity ranking and historical K-line adapter."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import load_config
from .ths import score_row as ths_score_row, fetch_history as ths_fetch_history
from ..engine.theme_catalog import theme_for

RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
CURL_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _float(value, default=0.0):
    try: return float(value)
    except (TypeError, ValueError): return default


def _board(code, configured=None):
    catalog = theme_for(code, "")
    if catalog: return catalog
    if configured and configured not in ("主板", "创业板", "科创板", "北交所"): return configured
    if code.startswith("688"): return "科创板"
    if code.startswith("30"): return "创业板"
    if code.startswith(("4", "8", "92")): return "北交所"
    return "主板"


def _secid(code):
    return ("1." if code.startswith("6") else "0.") + code


def fetch_rankings(page_size=None):
    cfg = load_config().get("collector", {}); page_size = int(page_size or cfg.get("eastmoney", {}).get("page_size", 30))
    body = json.dumps({"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "marketType": "", "pageNo": 1, "pageSize": page_size}).encode("utf-8")
    request = Request(RANK_URL, data=body, method="POST", headers={"User-Agent": "Mozilla/5.0 HeatFlow/0.6", "Content-Type": "application/json", "Origin": "https://guba.eastmoney.com", "Referer": "https://guba.eastmoney.com/"})
    with urlopen(request, timeout=int(cfg.get("timeout_seconds", 12))) as response: payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0 or not payload.get("data"): raise RuntimeError(payload.get("message") or "Eastmoney returned no ranking data")
    return payload["data"]


def fetch_history(code, limit=21):
    cfg = load_config().get("collector", {})
    params = {"secid": _secid(code), "klt": 101, "fqt": 1, "lmt": limit, "end": "20500101", "iscca": 1,
              "fields1": "f1,f2,f3,f4,f5,f6,f7,f8", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"}
    url = KLINE_URL + "?" + urlencode(params); timeout = int(cfg.get("timeout_seconds", 12))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/", "Accept": "application/json,text/plain,*/*", "Connection": "close"}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response: payload = json.loads(response.read().decode("utf-8"))
    except Exception as first_error:
        process = subprocess.run(["curl.exe", "--http1.1", "-sS", "--compressed", "-L", "--retry", "3", "--retry-all-errors", "--max-time", str(timeout), "-A", headers["User-Agent"], "-H", "Referer: https://quote.eastmoney.com/", url], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=CURL_FLAGS)
        try: payload = json.loads(process.stdout)
        except json.JSONDecodeError: return ths_fetch_history(code, limit)
    data = payload.get("data") or {}; candles = []
    for text in data.get("klines") or []:
        values = text.split(",")
        if len(values) < 11: continue
        candles.append({"date": values[0], "open": _float(values[1]), "close": _float(values[2]), "high": _float(values[3]), "low": _float(values[4]), "volume": _float(values[5]), "amount": _float(values[6]), "amplitude": _float(values[7]), "price_change": _float(values[8]), "change_amount": _float(values[9]), "turnover": _float(values[10])})
    if not candles: return ths_fetch_history(code, limit)
    return {"code": code, "name": data.get("name") or code, "candles": candles, "provider": "eastmoney_history"}


def _market_score(info):
    momentum = max(0, min(10, 5 + info.get("price_change", 0) / 4))
    turnover = max(0, min(10, info.get("turnover", 0) / 3))
    amplitude = max(0, min(10, info.get("amplitude", 0) / 2))
    return round(0.50 * momentum + 0.30 * turnover + 0.20 * amplitude, 2)


def collect(now=None, ths_rows=None):
    now = now or datetime.now(); rankings = fetch_rankings(); ths_rows = ths_rows or []
    ths_map = {row["code"]: row for row in ths_rows}; watchlist = load_config().get("collector", {}).get("watchlist", [])
    configured = {item["code"]: item for item in watchlist}; ranking_map = {}; codes = []
    for item in rankings:
        sc = str(item.get("sc", "")); code = sc[2:] if len(sc) >= 8 else ""
        if len(code) == 6 and code.isdigit(): codes.append(code); ranking_map[code] = item
    missing = [code for code in codes if code not in ths_map]; history_info = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_history, code, 3): code for code in missing}
        for future in as_completed(futures):
            try: history_info[futures[future]] = future.result()
            except Exception: pass
    output = []; market_dates = []
    total = max(len(codes), 2)
    for code in codes:
        ranking = ranking_map[code]; ths = ths_map.get(code); history = history_info.get(code)
        candle = history["candles"][-1] if history else {}
        name = (ths or {}).get("name") or (history or {}).get("name") or configured.get(code, {}).get("name") or code
        info = {**candle, **(ths or {})}; market_date = candle.get("date")
        if market_date: market_dates.append(market_date)
        rank = int(ranking.get("rk") or total); em_index = max(1.0, 10 - (rank - 1) * 7 / (total - 1))
        ths_index = ths_score_row(ths) if ths else _market_score(info)
        momentum = max(-1.2, min(1.2, _float(ranking.get("rc") or ranking.get("hisRc")) * 0.06))
        heat = 0.62 * em_index + 0.38 * ths_index
        output.append({"timestamp": "", "code": code, "name": name, "board": _board(code, (ths or configured.get(code, {})).get("board")),
            "price_change": info.get("price_change", 0), "turnover": info.get("turnover", 0), "heat_score": round(heat, 2), "final_score": round(max(0, heat + momentum), 2), "rank": rank,
            "sources": {"provider": "eastmoney+ths", "data_kind": "popularity_market", "eastmoney_rank": rank, "eastmoney_index": round(em_index, 2), "ths_index": round(ths_index, 2), "rank_momentum": round(momentum, 2), "last_price": info.get("last_price", info.get("close", 0)), "turnover": info.get("turnover", 0), "volume_ratio": info.get("volume_ratio", 0), "amplitude": info.get("amplitude", 0), "amount": info.get("amount", 0)}})
    if len(output) < 10: raise RuntimeError(f"Eastmoney/THS produced only {len(output)} stocks")
    source_date = max(market_dates) if market_dates else now.strftime("%Y-%m-%d")
    snapshot = now.isoformat(timespec="seconds") if source_date == now.strftime("%Y-%m-%d") else source_date + "T15:05:00"
    output.sort(key=lambda item: item["final_score"], reverse=True)
    for rank, row in enumerate(output, 1): row["timestamp"] = snapshot; row["rank"] = rank
    return output


def collect_history(days=7, now=None, items=None):
    items = items or load_config().get("collector", {}).get("watchlist", []); histories = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(items)))) as pool:
        futures = {pool.submit(ths_fetch_history, item["code"], max(days * 3, 21)): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try: data = future.result()
            except Exception:
                try: data = fetch_history(item["code"], max(days * 3, 21))
                except Exception: continue
            histories.append((item, data))
    dates = sorted({candle["date"] for _, data in histories for candle in data["candles"]})[-days:]; records = []
    for date_text in dates:
        current = []
        for item, data in histories:
            candle = next((value for value in data["candles"] if value["date"] == date_text), None)
            if not candle: continue
            score = _market_score(candle)
            current.append({"timestamp": date_text + "T15:00:00", "code": item["code"], "name": data.get("name") or item.get("name") or item["code"], "board": _board(item["code"], item.get("board")), "price_change": candle["price_change"], "heat_score": score, "final_score": score, "rank": 0,
                "sources": {"provider": data.get("provider", "eastmoney_history"), "data_kind": "daily_kline", **candle}})
        current.sort(key=lambda row: row["final_score"], reverse=True)
        for rank, row in enumerate(current, 1): row["rank"] = rank
        records.extend(current)
    if not records: raise RuntimeError("Eastmoney history returned no records")
    return records
