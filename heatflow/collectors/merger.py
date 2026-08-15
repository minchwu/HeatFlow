from datetime import datetime

from .mock import collect as mock_collect
from .eastmoney import collect as eastmoney_collect
from .ths import collect_market as ths_collect, score_row as ths_score_row
from .public_sentiment import collect_sentiment
from ..config import load_config
from ..db import save_collector_run, save_news_items


def _mock(now, provider="mock", reason="本地模拟采集"):
    rows = mock_collect(now)
    for row in rows:
        row["heat_score"] = round(row["heat_score"] / 10, 2); row["final_score"] = round(row["final_score"] / 10, 2)
        row.setdefault("sources", {})["provider"] = provider
        if provider == "mock_fallback": row["sources"]["fallback_reason"] = reason
    return rows


def _ths_fallback(rows, now):
    timestamp = (now or datetime.now()).isoformat(timespec="seconds"); output = []
    for item in rows[:30]:
        score = ths_score_row(item)
        output.append({"timestamp": timestamp, "code": item["code"], "name": item["name"], "board": item["board"], "price_change": item["price_change"], "turnover": item["turnover"], "heat_score": score, "final_score": score, "rank": 0,
            "sources": {"provider": "ths_fallback", "data_kind": "market_activity", "ths_index": score, "last_price": item["last_price"], "volume_ratio": item["volume_ratio"], "amplitude": item["amplitude"], "amount": item["amount"]}})
    output.sort(key=lambda row: row["final_score"], reverse=True)
    for rank, row in enumerate(output, 1): row["rank"] = rank
    return output


def _blend(rows, scores, statuses):
    weights = {"taoguba": 0.12, "cls": 0.10, "sina": 0.08, "wallstreetcn": 0.10}; active = {source for source, status in statuses.items() if status[0] == "ok"}
    for row in rows:
        numerator, denominator = row.get("final_score", 0) * 0.78, 0.78
        for source, weight in weights.items():
            value = scores.get(row["code"], {}).get(source, 0); row.setdefault("sources", {})[source] = round(value, 2)
            if source in active: numerator += value * weight; denominator += weight
        row["final_score"] = round(numerator / denominator, 2); row["heat_score"] = row["final_score"]
    rows.sort(key=lambda item: item["final_score"], reverse=True)
    for rank, row in enumerate(rows, 1): row["rank"] = rank
    return rows


def collect_all(now=None, mode="mock"):
    if mode == "mock":
        rows = _mock(now); save_collector_run("mock", "ok", len(rows), "本地模拟采集"); return rows
    ths_rows = []; ths_error = None
    try:
        ths_rows = ths_collect(); save_collector_run("ths", "ok", len(ths_rows), "同花顺A股行情中心")
    except Exception as exc:
        ths_error = str(exc); save_collector_run("ths", "error", 0, ths_error)
    try:
        base_rows = eastmoney_collect(now, ths_rows); save_collector_run("eastmoney", "ok", len(base_rows), "东方财富人气榜与历史行情")
    except Exception as exc:
        save_collector_run("eastmoney", "error", 0, str(exc))
        base_rows = _ths_fallback(ths_rows, now) if ths_rows else None
        if base_rows: save_collector_run("ths", "degraded", len(base_rows), "东方财富不可用，同花顺接管")
    if not base_rows:
        if not load_config().get("collector", {}).get("fallback_to_mock", True): raise RuntimeError("All configured live sources failed")
        base_rows = _mock(now, "mock_fallback", ths_error or "真实源不可用")
    scores, news_items, statuses = collect_sentiment(base_rows)
    for source, (status, message, count) in statuses.items(): save_collector_run(source, status, count, message)
    for item in news_items:
        related = [row["code"] for row in base_rows if row["name"] in item.get("title", "")]
        item["related_codes"] = related; item["heat_weight"] = min(10, len(related) * 2.5)
    save_news_items(news_items)
    return _blend(base_rows, scores, statuses)
