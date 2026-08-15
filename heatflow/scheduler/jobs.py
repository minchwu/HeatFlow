from datetime import datetime, time
import json
from ..collectors import collect_all
from ..collectors.eastmoney import collect_history
from ..collectors.market_timeline import collect_market_timeline
from ..collectors.market_breadth import fetch_market_breadth
from ..config import load_config, DATA_DIR
from ..db import init_db, save_records, latest_news, save_stock_profiles, get_stock_profiles, save_market_effect, save_market_breadth, recent_stock_history, save_market_timeline, save_collector_run, save_limit_reason_evidence
from ..engine.leaderboard import top10, main_theme, leader_tiers
from ..engine.sentiment import detect, metrics
from ..engine.logic_generate import generate
from ..engine.profile import build_profiles, build_market_insight
from ..engine.market_effect import evaluate, media_copy
from ..engine.reason_enrichment import build_reason_evidence
from ..report.exporter import export_report

def run_once(now=None, finalize=True):
    now = now or datetime.now(); init_db(); cfg = load_config()
    # The post-close job runs at 15:02 to avoid incomplete closing pools, but
    # its market snapshot belongs to 15:00.  Normalising this timestamp keeps
    # the exported race strictly inside the 09:30–15:00 session.
    snapshot_now = now
    if finalize and time(15, 0) <= now.time() < time(16, 0):
        snapshot_now = now.replace(hour=15, minute=0, second=0, microsecond=0)
    rows = collect_all(snapshot_now, cfg.get("collector", {}).get("mode", "mock")); save_records(rows)
    if cfg.get("collector", {}).get("mode") == "live":
        history_top_n = int(cfg.get("collector", {}).get("dynamic_history_top_n", 10))
        missing = []
        for row in rows[:history_top_n]:
            days = {item["timestamp"][:10] for item in recent_stock_history(row["code"], 80) if item.get("source_provider") in {"eastmoney+ths", "eastmoney_history", "ths_history", "ths_fallback"}}
            if len(days) < 5:
                missing.append({"code": row["code"], "name": row["name"], "board": row.get("board", "热点")})
        if missing:
            save_records(collect_history(days=7, now=now, items=missing))
    topics = latest_news(30); profile_rows = build_profiles(rows, topics); save_stock_profiles(profile_rows)
    breadth = None
    if cfg.get("collector", {}).get("mode") == "live":
        try:
            breadth = fetch_market_breadth(snapshot_now)
            save_market_breadth(breadth)
            save_collector_run("eastmoney_market_breadth", "ok", breadth["sample_size"], "东方财富全市场A股涨跌统计")
        except Exception as exc:
            save_collector_run("eastmoney_market_breadth", "limited", 0, str(exc))
    if cfg.get("collector", {}).get("mode") == "live" and breadth is None:
        # Do not silently substitute the hot-stock sample for whole-market
        # breadth; that would make the dashboard statistics misleading.
        effect = evaluate([], snapshot_now)
        effect.update({"date": rows[0]["timestamp"][:10] if rows else effect["date"], "label": "全市场数据暂不可用", "summary": "东方财富全市场涨跌统计暂不可用，未使用热股样本替代。", "data_scope": "东方财富全市场A股（接口暂不可用）"})
    else:
        effect = evaluate(rows, snapshot_now, breadth=breadth)
        effect["date"] = rows[0]["timestamp"][:10] if rows else effect["date"]
    save_market_effect(effect)
    top = top10(rows); insight = build_market_insight(rows, topics); theme = insight["theme"]; sentiment = detect(top); sentiment_metrics = metrics(top); leaders = leader_tiers(top)
    logic = insight["core_logic"] + "\n\n潜在机会：" + insight["opportunity"]; copy = media_copy(top, theme, sentiment, effect, topics, insight)
    data_time = datetime.fromisoformat(rows[0]["timestamp"]) if rows else now; date_text = data_time.strftime("%Y-%m-%d")
    try:
        timeline = collect_market_timeline(date_text)
        save_market_timeline(timeline["points"], timeline["events"])
        evidence_count = save_limit_reason_evidence(build_reason_evidence(date_text, timeline["events"], topics, snapshot_now.isoformat(timespec="seconds")))
        save_collector_run("eastmoney_market_timeline", "ok", len(timeline["points"]) + len(timeline["events"]), f"{date_text} index and limit events")
        save_collector_run("limit_reason_enrichment", "ok", evidence_count, "涨停原因多源证据归档")
    except Exception as exc:
        save_collector_run("eastmoney_market_timeline", "limited", 0, str(exc))
    if not finalize:
        return {"records": top, "effect": effect, "finalized": False}
    profiles = get_stock_profiles([row["code"] for row in top])
    folder = export_report(date_text, top, theme, sentiment, logic, copy, sentiment_metrics, leaders, effect, topics, profiles)
    return {"records": top, "report": folder, "metrics": sentiment_metrics, "leaders": leaders, "effect": effect, "finalized": True}

def backfill_week(now=None, days=None):
    cfg = load_config(); collector_cfg = cfg.get("collector", {})
    days = int(days or collector_cfg.get("history_days", 7))
    rows = collect_history(days=days, now=now); save_records(rows)
    report_folders = []
    for date_text in sorted({row["timestamp"][:10] for row in rows}):
        day_rows = [row for row in rows if row["timestamp"].startswith(date_text)]
        top = top10(day_rows); theme = main_theme(top); sentiment = detect(top)
        logic = generate(top, theme, sentiment)
        # Keep a dated market-effect snapshot for every recovered session so
        # the dashboard can freeze to the newest available trading day rather
        # than falling back to the first (often weeks-old) snapshot.  This is
        # explicitly marked as a hot-stock sample when whole-market breadth
        # was unavailable; it is never presented as 全A statistics.
        effect = evaluate(day_rows, datetime.fromisoformat(date_text + "T15:00:00"))
        effect["date"] = date_text
        copy = media_copy(top, theme, sentiment, effect)
        save_market_effect(effect)
        folder = export_report(date_text, top, theme, sentiment, logic, copy, metrics(top), leader_tiers(top), effect=effect)
        report_folders.append(str(folder))
        # Historical heat records alone are not enough for /tower. Also
        # backfill the index and limit-event timeline for every recovered
        # trading day so all three pages follow the same latest date.
        try:
            timeline = collect_market_timeline(date_text)
            save_market_timeline(timeline["points"], timeline["events"])
        except Exception as exc:
            save_collector_run("eastmoney_market_timeline", "limited", 0, f"历史回补 {date_text}：{exc}")
    return {"days": len(report_folders), "records": len(rows), "reports": report_folders}

def run_schedule():
    # Lightweight scheduler for MVP; use a Windows Task Scheduler entry to launch this script periodically.
    import time as _time
    collector_cfg = load_config().get("collector", {})
    interval = int(collector_cfg.get("interval_seconds") or collector_cfg.get("interval_minutes", 3) * 60)
    finalized_date = None
    while True:
        now = datetime.now()
        trading_day = now.weekday() < 5
        market_open = trading_day and bool(time(9, 30) <= now.time() <= time(15, 0))
        heartbeat = {"pid": __import__("os").getpid(), "checked_at": now.isoformat(timespec="seconds"), "market_hours": market_open, "trading_day": trading_day, "interval_seconds": interval}
        try:
            (DATA_DIR / "scheduler_heartbeat.json").write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")
        except OSError:
            # A dashboard read or antivirus scan can briefly lock this file;
            # heartbeat persistence must not terminate the collector loop.
            pass
        if market_open:
            try:
                run_once(now, finalize=False)
            except Exception as exc:
                save_collector_run("scheduler", "limited", 0, f"盘中采集失败：{exc}")
        elif trading_day and time(15, 2) <= now.time() <= time(15, 15) and finalized_date != now.date():
            try:
                run_once(now, finalize=True); finalized_date = now.date()
            except Exception as exc:
                save_collector_run("scheduler", "limited", 0, f"收盘生成失败：{exc}")
        _time.sleep(interval)
