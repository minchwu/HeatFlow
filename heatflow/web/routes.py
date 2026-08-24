from flask import Flask, jsonify, render_template, send_file, request
from pathlib import Path
import json
import os
import threading
import time as clock
from ..config import DATA_DIR, STATIC_DIR, APP_VERSION, load_config
from datetime import datetime, date, timedelta
from ..db import latest_records, records_for_date, get_report, db_summary, available_history_dates, available_tower_dates, history_overview, latest_news, get_stock_profiles, latest_market_effect, market_effect_on_or_before, latest_market_breadth, market_timeline
from ..engine.tower import build_tower
from ..engine.limit_review import build_limit_review
from ..engine.leaderboard import board_share, main_theme, leader_tiers
from ..engine.sentiment import detect, metrics, stage_tone
from ..engine.profile import build_market_insight, build_profiles
from ..engine.market_effect import media_copy
from ..collectors.status import source_status


_refresh_thread = None
_refresh_lock = threading.Lock()


def _last_weekday(value):
    """Return the nearest weekday used as the expected latest session."""
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _external_scheduler_is_fresh(now):
    """Avoid duplicating a separately launched --schedule process."""
    heartbeat = DATA_DIR / "scheduler_heartbeat.json"
    if not heartbeat.exists():
        return False
    try:
        payload = json.loads(heartbeat.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(str(payload.get("checked_at", "")))
        return int(payload.get("pid", 0)) != os.getpid() and (now - checked).total_seconds() < 35
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _write_background_heartbeat(now, market_open, interval):
    try:
        (DATA_DIR / "scheduler_heartbeat.json").write_text(json.dumps({
            "pid": os.getpid(), "checked_at": now.isoformat(timespec="seconds"),
            "market_hours": market_open, "trading_day": now.weekday() < 5,
            "interval_seconds": interval, "owner": "web-background-collector",
        }, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _background_collector_loop():
    """Keep the manually launched web service's database current.

    This replaces the fragile second terminal used by the old deployment:
    one daemon thread performs the same ten-second live collection and also
    recovers the most recent trading week when the database is stale.
    """
    from ..scheduler.jobs import run_once, backfill_week
    from ..db import save_collector_run

    cfg = load_config()
    if not cfg.get("collector", {}).get("auto_collect_on_start", True):
        return
    backfill_attempted = False
    finalized_date = None
    while True:
        now = datetime.now()
        trading_day = now.weekday() < 5
        market_open = trading_day and (datetime.min.time().replace(hour=9, minute=30) <= now.time() <= datetime.min.time().replace(hour=15))
        interval = 10 if market_open else int(cfg.get("collector", {}).get("closed_refresh_seconds", 30))
        try:
            if not backfill_attempted:
                latest = latest_records(1)
                latest_date = datetime.fromisoformat(latest[0]["timestamp"]).date() if latest else None
                expected = _last_weekday(now.date())
                if latest_date is None or latest_date < expected:
                    backfill_week(now=now, days=int(cfg.get("collector", {}).get("history_days", 7)))
                backfill_attempted = True
            if not _external_scheduler_is_fresh(now):
                if market_open:
                    run_once(now, finalize=False)
                elif trading_day and datetime.min.time().replace(hour=15, minute=2) <= now.time() <= datetime.min.time().replace(hour=15, minute=15) and finalized_date != now.date():
                    run_once(now, finalize=True)
                    finalized_date = now.date()
            _write_background_heartbeat(now, market_open, interval)
        except Exception as exc:
            try:
                save_collector_run("web_background_collector", "limited", 0, str(exc))
            except Exception:
                pass
        clock.sleep(max(10, interval))


def start_background_refresh():
    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread and _refresh_thread.is_alive():
            return
        _refresh_thread = threading.Thread(target=_background_collector_loop, name="heatflow-collector", daemon=True)
        _refresh_thread.start()


def important_event_nodes(reference=None):
    """Return near-term macro/event nodes used to anchor the hot-news panel."""
    ref = reference or date.today()
    nodes = [
        (date(ref.year, 8, 31), "半年报密集披露窗口", "业绩", "多数公司半年报集中披露，注意业绩预期与兑现差。"),
        (date(ref.year, 10, 31), "三季报密集披露窗口", "业绩", "三季报披露收官，关注景气度变化与商誉减值风险。"),
        (date(ref.year + 1, 4, 30), "年报与一季报密集披露窗口", "业绩", "年报、一季报集中披露，适合复核主线基本面。"),
        (date(ref.year, 9, 16), "美联储议息会议节点", "海外", "利率决议与点阵图可能影响北向资金和成长股估值。"),
        (date(ref.year, 11, 4), "美国财政部再融资/财政政策窗口", "海外", "美债供给与财政表态可能影响全球风险偏好。"),
        (date(ref.year + 1, 3, 5), "全国两会政策窗口", "政策", "人大会议与政府工作报告是全年政策主线的重要观察点。"),
    ]
    # Third Friday: index-futures/options delivery day, calculated rather than hard-coded.
    cursor = date(ref.year, ref.month, 1)
    for _ in range(5):
        first_friday = cursor + timedelta(days=(4 - cursor.weekday()) % 7)
        delivery = first_friday + timedelta(days=14)
        if delivery >= ref - timedelta(days=7):
            nodes.append((delivery, "股指期货/期权交割日", "交割", "交割周波动可能放大，留意尾盘基差和权重股异动。"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    output = []
    for event_date, title, category, detail in sorted(nodes, key=lambda item: item[0]):
        delta = (event_date - ref).days
        if -3 <= delta <= 120:
            urgency = "urgent" if delta <= 3 else "watch" if delta <= 14 else "normal"
            output.append({"date": event_date.isoformat(), "title": title, "category": category, "detail": detail, "days": delta, "urgency": urgency})
    return output[:12]

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder=str(STATIC_DIR), static_url_path="/static")
    @app.after_request
    def no_cache_dashboard(response):
        if request.path in {"/", "/history", "/tower"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response
    def mode_info(rows):
        provider = rows[0].get("source_provider", "unknown") if rows else "unknown"
        labels = {
            "eastmoney+ths": ("东方财富 × 同花顺", "live"),
            "ths_fallback": ("同花顺行情", "degraded"),
            "eastmoney_history": ("东方财富真实历史行情", "live"),
            "ths_history": ("同花顺真实历史行情", "live"),
            "mock_fallback": ("联网异常，已降级为模拟数据", "degraded"),
            "mock": ("本地模拟数据", "mock"),
        }
        label, state = labels.get(provider, (provider, "unknown"))
        return {"provider": provider, "label": label, "state": state}
    def display_effect(date_text):
        effect = latest_market_effect(date_text)
        if effect and effect.get("sample_size", 0) > 0 and "全市场A股" in effect.get("data_scope", ""):
            return effect
        # Outside trading hours the dashboard is a frozen view of the most
        # recent completed session. If a breadth snapshot is unavailable,
        # retain the latest settled effect instead of showing a blank/waiting
        # state to the user.
        previous = market_effect_on_or_before(date_text) or latest_market_effect()
        if previous:
            frozen = dict(previous)
            if "全市场A股" in str(previous.get("data_scope", "")):
                frozen["data_scope"] = "最近交易日全市场收盘（冻结）"
            else:
                frozen["data_scope"] = "最近交易日热股样本复盘（冻结）"
            frozen["frozen"] = True
            return frozen
        return {"sample_size": 0, "red_ratio": 0, "avg_change": 0, "strong_ratio": 0, "weak_ratio": 0,
                "label": "最近交易日无记录", "tone": "neutral", "summary": "暂无可用的最近交易时段结算信息。",
                "data_scope": "最近交易日收盘（冻结）", "frozen": True}
    @app.get("/")
    def index():
        rows = latest_records(20); series_date = rows[0]["timestamp"][:10] if rows else datetime.now().strftime("%Y-%m-%d")
        codes = [row["code"] for row in rows]; topics = latest_news(30)
        profiles = get_stock_profiles(codes)
        profiles.update({p["code"]: p for p in build_profiles(rows, topics)})
        effect = display_effect(series_date)
        stage = detect(rows); report = get_report(series_date); timeline = market_timeline(series_date)
        theme = main_theme(rows); insight = build_market_insight(rows, topics); important_events = important_event_nodes()
        rendered_copy = media_copy(rows, theme, stage, effect or {}, topics, insight)
        return render_template("index.html", records=rows, theme=theme, sentiment=stage, stage_tone=stage_tone(stage), metrics=metrics(rows), leaders=leader_tiers(rows), mode=mode_info(rows), data_timestamp=rows[0]["timestamp"] if rows else None, market_date=series_date, profiles=profiles, topics=topics[:8], important_events=important_events, effect=effect, report=report, rendered_copy=rendered_copy, timeline=timeline, version=APP_VERSION)
    @app.get("/api/latest")
    def api_latest():
        rows = latest_records(20); topics = latest_news(30)
        profiles = get_stock_profiles([row["code"] for row in rows])
        profiles.update({p["code"]: p for p in build_profiles(rows, topics)})
        series_date = rows[0]["timestamp"][:10] if rows else datetime.now().strftime("%Y-%m-%d")
        effect = display_effect(series_date)
        theme = main_theme(rows)
        sentiment = detect(rows)
        insight = build_market_insight(rows, topics)
        return jsonify({"records": rows, "profiles": profiles, "theme": theme,
                        "sentiment": sentiment, "shares": board_share(rows),
                        "metrics": metrics(rows), "leaders": leader_tiers(rows),
                        "mode": mode_info(rows), "market_date": series_date,
                        "data_timestamp": rows[0]["timestamp"] if rows else None,
                        "effect": effect,
                        "rendered_copy": media_copy(rows, theme, sentiment, effect, topics, insight)})
    @app.get("/api/hot-news")
    def api_hot_news():
        source_weight = {"ths": 1.0, "eastmoney": 1.0, "taoguba": .9, "sina": .85, "wallstreetcn": .9, "cls": .9}
        items = latest_news(40)
        for item in items:
            item["importance"] = round(float(item.get("heat_weight") or 0) * source_weight.get(item.get("source", ""), .7), 2)
            item["tone"] = "urgent" if item["importance"] >= 8 else "watch" if item["importance"] >= 4 else "normal"
        items.sort(key=lambda item: (item.get("importance", 0), item.get("id", 0)), reverse=True)
        return jsonify({"items": items[:20], "important_events": important_event_nodes()})
    @app.get("/api/version")
    def api_version():
        return jsonify({"version": APP_VERSION, "name": "HeatFlow"})
    @app.get("/favicon.ico")
    def favicon():
        response = send_file(STATIC_DIR / "youtianxia-logo.png", mimetype="image/png", max_age=0)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
    @app.get("/api/health")
    def api_health():
        summary = db_summary()
        heartbeat_path = DATA_DIR / "scheduler_heartbeat.json"; scheduler = {"ok": False, "message": "尚未检测到调度心跳"}
        if heartbeat_path.exists():
            try:
                scheduler = json.loads(heartbeat_path.read_text(encoding="utf-8")); scheduler["ok"] = True
            except (OSError, json.JSONDecodeError):
                scheduler = {"ok": False, "message": "调度心跳文件不可读"}
        return jsonify({"ok": True, "version": APP_VERSION, "database": summary, "market_breadth": latest_market_breadth(), "sources": source_status(), "scheduler": scheduler, "collector_mode": load_config().get("collector", {}).get("mode", "mock")})
    @app.get("/api/series/<date_text>")
    def api_series(date_text):
        rows = records_for_date(date_text)
        points = {}
        for row in rows:
            bucket = row["timestamp"][:16]
            points.setdefault(bucket, 0)
            points[bucket] = max(points[bucket], row.get("final_score", 0))
        return jsonify({"date": date_text, "points": [{"time": k, "value": v} for k, v in sorted(points.items())]})
    @app.get("/api/market-timeline/<date_text>")
    def api_market_timeline(date_text):
        return jsonify(market_timeline(date_text))
    @app.get("/api/market-timeline/latest")
    def api_latest_market_timeline():
        dates = available_tower_dates(1)
        date_text = dates[0]["date"] if dates else datetime.now().strftime("%Y-%m-%d")
        return jsonify(market_timeline(date_text))
    @app.get("/tower")
    def tower_page():
        dates = available_tower_dates(30)
        timeline_dates = [item["date"] for item in dates]
        default_date = timeline_dates[0] if timeline_dates else datetime.now().strftime("%Y-%m-%d")
        return render_template("tower.html", today=default_date, dates=timeline_dates,
                               tower=build_tower(default_date), version=APP_VERSION)
    @app.get("/limit-review")
    def limit_review_page():
        dates = available_tower_dates(30)
        review_dates = [item["date"] for item in dates]
        default_date = review_dates[0] if review_dates else datetime.now().strftime("%Y-%m-%d")
        return render_template("limit_review.html", today=default_date, dates=review_dates,
                               review=build_limit_review(default_date), version=APP_VERSION)
    @app.get("/api/limit-review/<date_text>")
    def api_limit_review(date_text):
        return jsonify(build_limit_review(date_text))
    @app.get("/api/limit-review/latest")
    def api_latest_limit_review():
        dates = available_tower_dates(1)
        date_text = dates[0]["date"] if dates else datetime.now().strftime("%Y-%m-%d")
        return jsonify(build_limit_review(date_text))
    @app.get("/api/tower/<date_text>")
    def api_tower(date_text):
        return jsonify(build_tower(date_text))
    @app.get("/api/tower/latest")
    def api_latest_tower():
        dates = available_tower_dates(1)
        date_text = dates[0]["date"] if dates else datetime.now().strftime("%Y-%m-%d")
        return jsonify(build_tower(date_text))
    @app.get("/history")
    def history_page():
        dates = available_history_dates(30); real_dates = [item for item in dates if item.get("is_real")]
        default_date = (real_dates or dates or [{"date": datetime.now().strftime("%Y-%m-%d")}])[0]["date"]
        return render_template("history.html", today=default_date, dates=dates, overview=history_overview(7), version=APP_VERSION)
    @app.get("/history/<date_text>")
    def history(date_text):
        rows = records_for_date(date_text)
        return jsonify({"date": date_text, "records": rows, "report": get_report(date_text), "mode": mode_info(rows), "effect": display_effect(date_text)})
    @app.get("/api/history/dates")
    def history_dates():
        return jsonify({"dates": available_history_dates(30), "overview": history_overview(7)})
    # Static-site export and CI render routes from the same templates, but
    # must not spawn a second collector while generating a frozen snapshot.
    if os.environ.get("HEATFLOW_DISABLE_BACKGROUND") != "1":
        start_background_refresh()
    return app
