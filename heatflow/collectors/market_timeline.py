"""Eastmoney intraday index and limit-up/limit-down event collector."""

from datetime import datetime
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import load_config
from ..engine.board_names import normalize_board

POOL_URLS = {
    "up": "https://push2ex.eastmoney.com/getTopicZTPool",
    "down": "https://push2ex.eastmoney.com/getTopicDTPool",
    "broken": "https://push2ex.eastmoney.com/getTopicZBPool",
}
TREND_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

# Eastmoney's limit-pool payload occasionally returns a four-character
# industry abbreviation even though the UI label is longer. Normalize those
# known abbreviations at ingestion so historical rows and live rows share the
# same complete board name.


def _get_json(url, params):
    timeout = int(load_config().get("collector", {}).get("timeout_seconds", 12))
    request = Request(url + "?" + urlencode(params), headers=HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _clock(value, fallback="09:30"):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit()).zfill(6)[-6:]
    hour, minute = int(digits[:2]), int(digits[2:4])
    if 9 <= hour <= 15 and minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return fallback


def _event_logic(item, direction, state):
    industry = normalize_board(item.get("hybk") or item.get("bk") or item.get("industry"))
    board_count = int(item.get("lbc") or (item.get("zttj") or {}).get("ct") or 1)
    if direction == "down":
        action = "跌停承压" if state != "opened" else "跌停开板"
    elif state == "broken":
        action = "冲板后炸板"
    elif board_count > 1:
        action = f"{board_count}连板强化"
    else:
        action = "资金封板确认"
    return f"{industry}｜{action}"


def fetch_limit_events(date_text):
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 300,
        "sort": "fbt:asc",
        "date": date_text.replace("-", ""),
    }
    events = []
    for kind, url in POOL_URLS.items():
        try:
            pool = ((_get_json(url, params).get("data") or {}).get("pool") or [])
        except Exception:
            continue
        for item in pool:
            code = str(item.get("c") or item.get("code") or "").zfill(6)
            name = item.get("n") or item.get("name") or code
            if len(code) != 6:
                continue
            if kind == "up":
                direction, state, final_state = "up", "sealed", "up_limit"
            elif kind == "down":
                direction, state, final_state = "down", "sealed", "down_limit"
            else:
                direction, state, final_state = "up", "broken", "broken"
            event_time = _clock(item.get("fbt") or item.get("first_time") or item.get("lbt"))
            events.append({
                "date": date_text,
                "event_time": f"{date_text}T{event_time}:00",
                "code": code,
                "name": name,
                "direction": direction,
                "state": state,
                "final_state": final_state,
                "price_change": float(item.get("zdp") or item.get("change") or 0),
                "board": normalize_board(item.get("hybk") or item.get("bk") or item.get("industry")),
                "logic_text": _event_logic(item, direction, state),
                "source": "eastmoney_limit_pool",
                "metadata": {
                    "first_limit_time": _clock(item.get("fbt")),
                    "last_limit_time": _clock(item.get("lbt")),
                    "open_count": int(item.get("zbc") or 0),
                    "board_count": int(item.get("lbc") or 1),
                },
            })
    # A stock may appear in a provisional pool and the final broken pool. Closing state wins.
    priority = {"broken": 3, "down_limit": 2, "up_limit": 1}
    final = {}
    for item in events:
        old = final.get(item["code"])
        if not old or priority[item["final_state"]] >= priority[old["final_state"]]:
            final[item["code"]] = item
    return sorted(final.values(), key=lambda item: item["event_time"])


def fetch_index_points(date_text, secid="1.000001", name="上证指数"):
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "ndays": 1,
        "iscr": 0,
        "iscca": 0,
        "secid": secid,
    }
    data = _get_json(TREND_URL, params).get("data") or {}
    pre_close = float(data.get("preClose") or 0)
    points = []
    for value in data.get("trends") or []:
        fields = value.split(",")
        if len(fields) < 3 or not fields[0].startswith(date_text):
            continue
        price = float(fields[2])
        points.append({
            "date": date_text,
            "timestamp": fields[0].replace(" ", "T") + ":00",
            "index_code": secid,
            "index_name": data.get("name") or name,
            "value": price,
            "price_change": round((price / pre_close - 1) * 100, 3) if pre_close else 0,
            "source": "eastmoney_trends",
        })
    return points


def collect_market_timeline(date_text=None):
    date_text = date_text or datetime.now().strftime("%Y-%m-%d")
    return {
        "date": date_text,
        "points": fetch_index_points(date_text),
        "events": fetch_limit_events(date_text),
    }
