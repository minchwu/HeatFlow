"""One-minute replay data for the HeatFlow Limit-Up / Limit-Down Tower."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..db import market_timeline


def _minute(value, fallback=570):
    """Read ``HH:MM`` or an ISO timestamp into minutes after midnight."""
    try:
        parts = str(value or "")[-8:].split(":")
        hour, minute = (int(part) for part in (parts[:2] if len(parts) == 3 else parts[-2:]))
        return hour * 60 + minute
    except (TypeError, ValueError):
        return fallback


def _clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def _frame_minutes(interval=1):
    """Trading minutes without a fabricated noon-session transition."""
    return [565, *range(570, 691, interval), *range(780, 901, interval)]


def _normalise_event(event):
    meta = event.get("metadata") or {}
    first = _minute(meta.get("first_limit_time") or event.get("event_time"))
    last = _minute(meta.get("last_limit_time") or event.get("event_time"), first)
    final_state = event.get("final_state") or event.get("state") or "up_limit"
    direction = "down" if event.get("direction") == "down" else "up"
    opened = final_state in {"broken", "opened"} or event.get("state") in {"broken", "opened"}
    return {
        "code": str(event.get("code") or ""),
        "name": str(event.get("name") or "未知个股"),
        "sector": str(event.get("board") or "市场热点"),
        "board": max(1, int(meta.get("board_count") or 1)),
        "first": first,
        "last": max(first, last),
        "direction": direction,
        "opened": opened,
        "final_state": final_state,
        "price_change": float(event.get("price_change") or 0),
        "logic": str(event.get("logic_text") or ""),
        "open_count": max(0, int(meta.get("open_count") or 0)),
    }


def _dedupe(events):
    """One stock has one current state per direction in the event pool."""
    result = {}
    for item in events:
        key = (item["direction"], item["code"])
        before = result.get(key)
        if before is None or (item["last"], item["board"], item["opened"]) > (before["last"], before["board"], before["opened"]):
            result[key] = item
    return sorted(result.values(), key=lambda item: (item["first"], item["sector"], item["code"]))


def _transition_index(transitions):
    """Index verified intraday state changes by stock and direction."""
    output = {}
    for item in transitions or []:
        if item.get("direction") != "up" or item.get("event_type") not in {"BREAK", "RESEAL"}:
            continue
        key = (item.get("direction"), str(item.get("code") or ""))
        output.setdefault(key, []).append({
            "minute": _minute(item.get("event_time")),
            "event_type": item.get("event_type"),
            "event_time": item.get("event_time"),
        })
    for rows in output.values():
        rows.sort(key=lambda item: (item["minute"], item["event_time"]))
    return output


def _brick(event, frame_minute, previous=False, transitions=()):
    if previous:
        status = "previous"
    else:
        status = "down_limit" if event["direction"] == "down" else "limit_up"
        known_break = False
        for turn in transitions:
            if turn["minute"] > frame_minute:
                break
            if turn["event_type"] == "BREAK":
                status = "opened" if event["direction"] == "down" else "broken"
                known_break = True
            elif turn["event_type"] == "RESEAL":
                status = "down_limit" if event["direction"] == "down" else "limit_up"
        # Historical pool data has a reliable final broken time but no full
        # state sequence. Use it only when there is no verified transition.
        if event["opened"] and not known_break and frame_minute >= event["last"]:
            status = "opened" if event["direction"] == "down" else "broken"
        if status in {"limit_up", "down_limit"} and frame_minute == event["first"]:
            status = "new_down" if event["direction"] == "down" else "new_limit"
    return {
        "code": event["code"], "name": event["name"], "sector": event["sector"],
        "board": event["board"], "direction": event["direction"], "status": status,
        "price_change": event["price_change"], "logic": event["logic"],
        "first_limit_time": _clock(event["first"]), "last_limit_time": _clock(event["last"]),
        "open_count": event["open_count"],
    }


def _previous_session_bricks(date_text):
    """Nearest previous closed session, rendered gray at the 09:25 seed."""
    try:
        cursor = datetime.strptime(date_text, "%Y-%m-%d").date() - timedelta(days=1)
    except ValueError:
        return [], None
    for _ in range(10):
        raw = market_timeline(cursor.isoformat())
        prior = [_normalise_event(event) for event in raw.get("events", []) if event.get("direction") == "up"]
        prior = [item for item in _dedupe(prior) if not item["opened"]]
        if prior:
            return [_brick(item, 565, previous=True) for item in prior], cursor.isoformat()
        cursor -= timedelta(days=1)
    return [], None


def _index_points(raw):
    """Choose the most complete major-index series from the timeline feed."""
    groups = {}
    for point in raw.get("indices", []):
        groups.setdefault(point.get("index_code") or point.get("index_name") or "market", []).append(point)
    if not groups:
        return []
    series = max(groups.values(), key=lambda items: (len(items), str(items[0].get("index_code", ""))))
    return sorted(series, key=lambda item: item.get("timestamp", ""))


def _index_at(points, frame_minute):
    current = None
    for point in points:
        if _minute(point.get("timestamp"), 0) <= frame_minute:
            current = point
        else:
            break
    if current is None:
        return {"name": "大盘指数", "value": None, "change": None}
    return {
        "name": current.get("index_name") or "大盘指数",
        "value": round(float(current.get("value") or 0), 2),
        "change": round(float(current.get("price_change") or 0), 2),
    }


def _events_log(events, transitions):
    """Combine static pool facts with verified 10-second state transitions."""
    log = []
    relevant = {}
    for turn in transitions or []:
        if turn.get("direction") == "up":
            relevant.setdefault(str(turn.get("code") or ""), []).append(turn)
    for item in events:
        enter = "UPGRADE" if item["board"] > 1 else "NEW_LIMIT"
        log.append({"time": _clock(item["first"]), "type": enter, "code": item["code"],
                    "name": item["name"], "sector": item["sector"],
                    "from_board": max(0, item["board"] - 1), "to_board": item["board"],
                    "open_count": item["open_count"]})
        turns = relevant.get(item["code"], [])
        has_break = False
        has_reopen_note = False
        for turn in turns:
            kind = turn.get("event_type")
            if kind == "BREAK":
                has_break = True
                event_type = "BREAK_CONTINUE" if item["board"] > 1 else "BREAK_FIRST"
            elif kind == "RESEAL":
                event_type = "RESEAL"
            elif kind == "REOPENED":
                has_reopen_note = True
                event_type = "REOPENED"
            else:
                continue
            log.append({"time": _clock(_minute(turn.get("event_time"))), "type": event_type,
                        "code": item["code"], "name": item["name"], "sector": item["sector"],
                        "from_board": item["board"], "to_board": item["board"],
                        "open_count": item["open_count"]})
        if item["opened"] and not has_break:
            leave = "BREAK_CONTINUE" if item["board"] > 1 else "BREAK_FIRST"
            log.append({"time": _clock(item["last"]), "type": leave, "code": item["code"],
                        "name": item["name"], "sector": item["sector"],
                        "from_board": item["board"], "to_board": item["board"],
                        "open_count": item["open_count"]})
        if item["open_count"] and not has_reopen_note and not item["opened"]:
            log.append({"time": _clock(item["last"]), "type": "REOPENED", "code": item["code"],
                        "name": item["name"], "sector": item["sector"],
                        "from_board": item["board"], "to_board": item["board"],
                        "open_count": item["open_count"]})
    return sorted(log, key=lambda item: (item["time"], item["code"], item["type"]))


def build_tower(date_text, interval=1):
    """Return one-minute limit-up distribution frames grouped by board height."""
    raw = market_timeline(date_text)
    events = _dedupe([_normalise_event(event) for event in raw.get("events", [])])
    up_events = [item for item in events if item["direction"] == "up"]
    transition_index = _transition_index(raw.get("transitions", []))
    previous_bricks, _ = _previous_session_bricks(date_text)
    index_points = _index_points(raw)
    frames = []
    for frame_minute in _frame_minutes(interval):
        up_bricks = (previous_bricks if frame_minute == 565 else
                     [_brick(item, frame_minute, transitions=transition_index.get(("up", item["code"]), []))
                      for item in up_events if item["first"] <= frame_minute])
        up_active = [item for item in up_bricks if item["status"] not in {"broken"}]
        current_high = max((item["board"] for item in up_active), default=0)
        frames.append({
            "time": _clock(frame_minute), "minute": frame_minute,
            "up_bricks": up_bricks,
            "metrics": {
                "highest_board": current_high, "sealed": len(up_active),
                "broken": len(up_bricks) - len(up_active),
                "first_board": sum(item["board"] == 1 for item in up_active if item["status"] != "previous"),
                "continuation": sum(item["board"] >= 2 for item in up_active if item["status"] != "previous"),
                "market_index": _index_at(index_points, frame_minute),
            },
        })
    final = frames[-1]["metrics"] if frames else {}
    return {"date": date_text, "interval_minutes": interval, "frames": frames,
            "event_log": _events_log(up_events, raw.get("transitions", [])), "final": final, "source": "limit_events",
            "distribution_rule": "所有涨停按连板高度分层；每层最多七列，层内按板块封板数量和首次涨停时间排序，炸板沉入对应板高的炸板区",
            "generated_at": datetime.now().isoformat(timespec="seconds")}
