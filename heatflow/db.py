import json
import sqlite3
from datetime import datetime
from .config import DATA_DIR, ensure_dirs
from .engine.board_names import normalize_board

DB_PATH = DATA_DIR / "heat.db"

def connect():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (code TEXT PRIMARY KEY, name TEXT NOT NULL, board TEXT);
        CREATE TABLE IF NOT EXISTS heat_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, code TEXT NOT NULL,
            heat_score REAL NOT NULL, rank INTEGER NOT NULL, price_change REAL DEFAULT 0, board TEXT,
            final_score REAL DEFAULT 0, source_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_heat_time ON heat_records(timestamp);
        CREATE TABLE IF NOT EXISTS daily_reports (
            date TEXT PRIMARY KEY, top10_json TEXT, main_theme TEXT, sentiment_stage TEXT,
            logic_text TEXT, douyin_copy TEXT, gif_path TEXT, video_path TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS collector_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT NOT NULL, source TEXT NOT NULL,
            status TEXT NOT NULL, record_count INTEGER DEFAULT 0, message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_collector_run_at ON collector_runs(run_at);
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, published_at TEXT,
            title TEXT NOT NULL, url TEXT, category TEXT, related_codes TEXT,
            heat_weight REAL DEFAULT 0, collected_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_news_collected ON news_items(collected_at);
        CREATE TABLE IF NOT EXISTS limit_reason_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, code TEXT NOT NULL,
            stock_name TEXT NOT NULL, board TEXT, concept TEXT, catalyst_type TEXT NOT NULL,
            evidence_text TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT,
            confidence REAL DEFAULT 0, evidence_json TEXT, collected_at TEXT NOT NULL,
            UNIQUE(date,code,source,evidence_text)
        );
        CREATE INDEX IF NOT EXISTS idx_limit_reason_date ON limit_reason_evidence(date,code,confidence);
        CREATE TABLE IF NOT EXISTS stock_profiles (
            code TEXT PRIMARY KEY, speculation_logic TEXT, stock_character TEXT,
            tags_json TEXT, evidence_json TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS market_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, date TEXT NOT NULL,
            sample_size INTEGER, red_ratio REAL, avg_change REAL, strong_ratio REAL,
            weak_ratio REAL, heat_concentration REAL, label TEXT, summary TEXT, data_scope TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_market_effect_date ON market_effects(date,timestamp);
        CREATE TABLE IF NOT EXISTS market_breadth_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, date TEXT NOT NULL,
            sample_size INTEGER NOT NULL, up_count INTEGER DEFAULT 0, down_count INTEGER DEFAULT 0,
            flat_count INTEGER DEFAULT 0, red_ratio REAL DEFAULT 0, avg_change REAL DEFAULT 0,
            strong_ratio REAL DEFAULT 0, weak_ratio REAL DEFAULT 0, source TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_market_breadth_date ON market_breadth_snapshots(date,timestamp);
        CREATE TABLE IF NOT EXISTS market_index_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, timestamp TEXT NOT NULL,
            index_code TEXT NOT NULL, index_name TEXT NOT NULL, value REAL NOT NULL,
            price_change REAL DEFAULT 0, source TEXT NOT NULL,
            UNIQUE(timestamp,index_code,source)
        );
        CREATE INDEX IF NOT EXISTS idx_index_points_date ON market_index_points(date,timestamp);
        CREATE TABLE IF NOT EXISTS limit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, event_time TEXT NOT NULL,
            collected_at TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            direction TEXT NOT NULL, state TEXT NOT NULL, final_state TEXT NOT NULL,
            price_change REAL DEFAULT 0, board TEXT, logic_text TEXT, source TEXT NOT NULL,
            metadata_json TEXT, UNIQUE(date,code,source)
        );
        CREATE INDEX IF NOT EXISTS idx_limit_events_date ON limit_events(date,event_time);
        CREATE TABLE IF NOT EXISTS limit_event_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, observed_at TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, direction TEXT NOT NULL, pool_state TEXT NOT NULL,
            final_state TEXT NOT NULL, board TEXT, board_count INTEGER DEFAULT 1, price_change REAL DEFAULT 0,
            source TEXT NOT NULL, metadata_json TEXT,
            UNIQUE(date,observed_at,code,direction)
        );
        CREATE INDEX IF NOT EXISTS idx_limit_snapshot_date ON limit_event_snapshots(date,code,direction,id);
        CREATE TABLE IF NOT EXISTS limit_event_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, event_time TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, direction TEXT NOT NULL, event_type TEXT NOT NULL,
            board TEXT, board_count INTEGER DEFAULT 1, price_change REAL DEFAULT 0,
            source TEXT NOT NULL, metadata_json TEXT,
            UNIQUE(date,event_time,code,direction,event_type)
        );
        CREATE INDEX IF NOT EXISTS idx_limit_transition_date ON limit_event_transitions(date,event_time);
        CREATE TABLE IF NOT EXISTS tower_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, event_time TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, sector TEXT, event_type TEXT NOT NULL,
            from_board INTEGER DEFAULT 0, to_board INTEGER DEFAULT 1, status TEXT,
            price REAL DEFAULT 0, reason TEXT, metadata_json TEXT,
            UNIQUE(date,event_time,code,event_type)
        );
        CREATE INDEX IF NOT EXISTS idx_tower_events_date ON tower_events(date,event_time);
        CREATE TABLE IF NOT EXISTS tower_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, snapshot_time TEXT NOT NULL,
            board_level INTEGER NOT NULL, code TEXT NOT NULL, status TEXT NOT NULL,
            sector TEXT, x INTEGER DEFAULT 0, y INTEGER DEFAULT 0, metadata_json TEXT,
            UNIQUE(date,snapshot_time,code)
        );
        CREATE INDEX IF NOT EXISTS idx_tower_snapshots_date ON tower_snapshots(date,snapshot_time);
        """)
        _ensure_column(c, "daily_reports", "race_gif_path", "TEXT")
        _ensure_column(c, "daily_reports", "race_video_path", "TEXT")
        _ensure_column(c, "daily_reports", "market_effect_json", "TEXT")
        _ensure_column(c, "market_effects", "tone", "TEXT")

def _ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def save_records(records):
    init_db()
    with connect() as c:
        for r in records:
            board = normalize_board(r.get("board", ""))
            c.execute("INSERT OR REPLACE INTO stocks(code,name,board) VALUES(?,?,?)", (r["code"], r["name"], board))
            provider = str(r.get("sources", {}).get("provider", ""))
            duplicate = c.execute(
                "SELECT 1 FROM heat_records WHERE timestamp=? AND code=? AND source_json LIKE ? LIMIT 1",
                (r["timestamp"], r["code"], f"%{provider}%"),
            ).fetchone()
            if duplicate:
                continue
            c.execute("""INSERT INTO heat_records(timestamp,code,heat_score,rank,price_change,board,final_score,source_json)
                        VALUES(?,?,?,?,?,?,?,?)""", (r["timestamp"], r["code"], r["heat_score"], r["rank"], r.get("price_change", 0), board, r.get("final_score", r["heat_score"]), json.dumps(r.get("sources", {}), ensure_ascii=False)))

def latest_records(limit=10):
    init_db()
    with connect() as c:
        # Select the newest timestamp across every real collector.  The old
        # implementation permanently preferred the newest eastmoney+ths
        # snapshot, which left the homepage pinned to an old date even after
        # historical eastmoney/ths records had been backfilled.
        real_time = c.execute("""
            SELECT MAX(timestamp) AS t
            FROM heat_records
            WHERE json_extract(source_json,'$.provider') IN
                ('eastmoney+ths','eastmoney_history','ths_history','ths_fallback')
        """).fetchone()["t"]
        if real_time:
            rows = c.execute("""SELECT h.*,s.name FROM heat_records h JOIN stocks s ON s.code=h.code
                WHERE h.timestamp=?
                  AND json_extract(h.source_json,'$.provider') IN
                    ('eastmoney+ths','eastmoney_history','ths_history','ths_fallback')
                ORDER BY h.final_score DESC LIMIT ?""", (real_time, limit)).fetchall()
        else:
            timestamp = c.execute("SELECT MAX(timestamp) AS t FROM heat_records").fetchone()["t"]
            rows = c.execute("""SELECT h.*,s.name FROM heat_records h JOIN stocks s ON s.code=h.code
                WHERE h.timestamp=? ORDER BY h.rank LIMIT ?""", (timestamp, limit)).fetchall()
    output = [_decode_row(r) for r in rows]
    for rank, row in enumerate(output, 1):
        row["rank"] = rank
    return output

def records_for_date(date_text):
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT h.*,s.name FROM heat_records h JOIN stocks s ON s.code=h.code
                           WHERE substr(h.timestamp,1,10)=? ORDER BY h.timestamp,h.rank""", (date_text,)).fetchall()
    decoded = [_decode_row(r) for r in rows]
    active_providers = {"eastmoney+ths", "eastmoney_history", "ths_history", "ths_fallback"}
    active = [row for row in decoded if row.get("source_provider") in active_providers]
    return active or decoded

def _decode_row(row):
    item = dict(row)
    # Heat snapshots collected before the canonical-name fixes may still
    # contain abbreviated sector labels. Normalize on every read so old
    # history is corrected immediately without requiring a database rewrite.
    item["board"] = normalize_board(item.get("board"))
    try:
        item["sources"] = json.loads(item.get("source_json") or "{}")
    except json.JSONDecodeError:
        item["sources"] = {}
    item["source_provider"] = item["sources"].get("provider", "unknown")
    return item

def save_collector_run(source, status, record_count=0, message=""):
    init_db()
    with connect() as c:
        c.execute(
            "INSERT INTO collector_runs(run_at,source,status,record_count,message) VALUES(?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), source, status, record_count, str(message)[:500]),
        )

def latest_collector_runs():
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT r.* FROM collector_runs r
            JOIN (SELECT source, MAX(id) AS id FROM collector_runs GROUP BY source) x ON x.id=r.id
            ORDER BY r.source""").fetchall()
    return [dict(row) for row in rows]

def available_history_dates(limit=14):
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT substr(timestamp,1,10) AS date, COUNT(*) AS records,
            COUNT(DISTINCT timestamp) AS snapshots,
            MAX(CASE WHEN json_extract(source_json,'$.provider') IN ('eastmoney+ths','eastmoney_history','ths_history','ths_fallback') THEN 1 ELSE 0 END) AS is_real
            FROM heat_records GROUP BY substr(timestamp,1,10) ORDER BY date DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(row) for row in rows]

def available_tower_dates(limit=30):
    """Dates with limit-event data, independent of heat-record retention."""
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT date, COUNT(*) AS events,
            SUM(CASE WHEN direction='up' THEN 1 ELSE 0 END) AS up_events
            FROM limit_events GROUP BY date ORDER BY date DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(row) for row in rows]

def history_overview(limit=7):
    candidates = available_history_dates(max(limit * 3, 21))
    real_days = [day for day in candidates if day.get("is_real")]
    days = (real_days or candidates)[:limit]
    overview = []
    for day in days:
        rows = records_for_date(day["date"])
        if not rows:
            continue
        top = max(rows, key=lambda row: row.get("final_score", 0))
        overview.append({
            **day,
            "top_name": top.get("name", ""),
            "top_score": round(top.get("final_score", 0), 1),
            "avg_change": round(sum(row.get("price_change", 0) for row in rows) / len(rows), 2),
        })
    return overview

def save_report(report):
    with connect() as c:
        c.execute("""INSERT OR REPLACE INTO daily_reports(date,top10_json,main_theme,sentiment_stage,logic_text,douyin_copy,gif_path,video_path,created_at,race_gif_path,race_video_path,market_effect_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (report["date"], json.dumps(report["top10"], ensure_ascii=False), report.get("main_theme", ""), report.get("sentiment_stage", ""), report.get("logic_text", ""), report.get("douyin_copy", ""), report.get("gif_path", ""), report.get("video_path", ""), datetime.now().isoformat(timespec="seconds"), report.get("race_gif_path", ""), report.get("race_video_path", ""), json.dumps(report.get("market_effect", {}), ensure_ascii=False)))

def save_news_items(items, collected_at=None):
    if not items:
        return 0
    init_db(); collected_at = collected_at or datetime.now().isoformat(timespec="seconds"); saved = 0
    with connect() as c:
        for item in items:
            duplicate = c.execute("SELECT 1 FROM news_items WHERE source=? AND title=? LIMIT 1", (item.get("source", "unknown"), item.get("title", ""))).fetchone()
            if duplicate or not item.get("title"):
                continue
            c.execute("""INSERT INTO news_items(source,published_at,title,url,category,related_codes,heat_weight,collected_at)
                VALUES(?,?,?,?,?,?,?,?)""", (item.get("source", "unknown"), item.get("published_at"), item["title"], item.get("url", ""), item.get("category", ""), json.dumps(item.get("related_codes", []), ensure_ascii=False), item.get("heat_weight", 0), collected_at))
            saved += 1
    return saved

def latest_news(limit=20):
    init_db()
    with connect() as c:
        rows = c.execute("SELECT * FROM news_items ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]

def save_limit_reason_evidence(items):
    """Persist traceable reason evidence; duplicate collector passes are safe."""
    if not items:
        return 0
    init_db(); saved = 0
    with connect() as c:
        for item in items:
            cursor = c.execute("""INSERT OR IGNORE INTO limit_reason_evidence
                (date,code,stock_name,board,concept,catalyst_type,evidence_text,source,source_url,confidence,evidence_json,collected_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                item["date"], item["code"], item.get("stock_name", item["code"]),
                normalize_board(item.get("board")), item.get("concept", "其他题材"),
                item.get("catalyst_type", "板块联动"), item.get("evidence_text", ""),
                item.get("source", "unknown"), item.get("source_url", ""),
                float(item.get("confidence", 0)), json.dumps(item.get("metadata", {}), ensure_ascii=False),
                item.get("collected_at") or datetime.now().isoformat(timespec="seconds"),
            ))
            saved += int(cursor.rowcount > 0)
    return saved

def limit_reason_evidence_for_date(date_text):
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT date,code,stock_name,board,concept,catalyst_type,evidence_text,
            source,source_url,confidence,evidence_json,collected_at
            FROM limit_reason_evidence WHERE date=?
            ORDER BY code,confidence DESC,id DESC""", (date_text,)).fetchall()
    output = []
    for row in rows:
        item = dict(row); item["board"] = normalize_board(item.get("board"))
        try:
            item["metadata"] = json.loads(item.pop("evidence_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        output.append(item)
    return output

def save_stock_profiles(profiles):
    if not profiles:
        return
    init_db()
    with connect() as c:
        for profile in profiles:
            c.execute("""INSERT OR REPLACE INTO stock_profiles(code,speculation_logic,stock_character,tags_json,evidence_json,updated_at)
                VALUES(?,?,?,?,?,?)""", (profile["code"], profile.get("speculation_logic", ""), profile.get("stock_character", ""), json.dumps(profile.get("tags", []), ensure_ascii=False), json.dumps(profile.get("evidence", {}), ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))

def get_stock_profiles(codes=None):
    init_db()
    with connect() as c:
        if codes:
            marks = ",".join("?" for _ in codes)
            rows = c.execute(f"SELECT * FROM stock_profiles WHERE code IN ({marks})", tuple(codes)).fetchall()
        else:
            rows = c.execute("SELECT * FROM stock_profiles ORDER BY updated_at DESC").fetchall()
    output = {}
    for row in rows:
        item = dict(row)
        item["tags"] = json.loads(item.get("tags_json") or "[]")
        item["evidence"] = json.loads(item.get("evidence_json") or "{}")
        output[item["code"]] = item
    return output

def recent_stock_history(code, limit=30):
    init_db()
    with connect() as c:
        rows = c.execute("""SELECT h.*,s.name FROM heat_records h JOIN stocks s ON s.code=h.code
            WHERE h.code=? ORDER BY h.timestamp DESC LIMIT ?""", (code, limit)).fetchall()
    return [_decode_row(row) for row in rows]

def save_market_effect(effect):
    init_db()
    with connect() as c:
        c.execute("""INSERT INTO market_effects(timestamp,date,sample_size,red_ratio,avg_change,strong_ratio,weak_ratio,heat_concentration,label,summary,data_scope,tone)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (effect["timestamp"], effect["date"], effect.get("sample_size", 0), effect.get("red_ratio", 0), effect.get("avg_change", 0), effect.get("strong_ratio", 0), effect.get("weak_ratio", 0), effect.get("heat_concentration", 0), effect.get("label", ""), effect.get("summary", ""), effect.get("data_scope", ""), effect.get("tone", "neutral")))

def save_market_breadth(snapshot):
    init_db()
    with connect() as c:
        c.execute("""INSERT INTO market_breadth_snapshots
            (timestamp,date,sample_size,up_count,down_count,flat_count,red_ratio,avg_change,strong_ratio,weak_ratio,source)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (snapshot["timestamp"], snapshot["date"], snapshot.get("sample_size", 0),
            snapshot.get("up_count", 0), snapshot.get("down_count", 0), snapshot.get("flat_count", 0),
            snapshot.get("red_ratio", 0), snapshot.get("avg_change", 0), snapshot.get("strong_ratio", 0),
            snapshot.get("weak_ratio", 0), snapshot.get("source", "unknown")))

def latest_market_breadth(date_text=None):
    init_db()
    with connect() as c:
        if date_text:
            row = c.execute("SELECT * FROM market_breadth_snapshots WHERE date=? ORDER BY timestamp DESC,id DESC LIMIT 1", (date_text,)).fetchone()
        else:
            row = c.execute("SELECT * FROM market_breadth_snapshots ORDER BY timestamp DESC,id DESC LIMIT 1").fetchone()
    return dict(row) if row else None

def latest_market_effect(date_text=None):
    init_db()
    with connect() as c:
        if date_text:
            row = c.execute("SELECT * FROM market_effects WHERE date=? ORDER BY timestamp DESC,id DESC LIMIT 1", (date_text,)).fetchone()
        else:
            row = c.execute("SELECT * FROM market_effects ORDER BY timestamp DESC,id DESC LIMIT 1").fetchone()
    return dict(row) if row else None

def market_effect_on_or_before(date_text):
    """Return the most recent completed market effect at or before a date."""
    init_db()
    with connect() as c:
        row = c.execute("""SELECT * FROM market_effects
            WHERE date<=? AND sample_size>0
            ORDER BY date DESC,timestamp DESC,id DESC LIMIT 1""", (date_text,)).fetchone()
    return dict(row) if row else None

def save_market_timeline(points, events):
    init_db()
    collected_at = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        for point in points or []:
            c.execute("""INSERT OR REPLACE INTO market_index_points
                (date,timestamp,index_code,index_name,value,price_change,source)
                VALUES(?,?,?,?,?,?,?)""", (point["date"], point["timestamp"], point["index_code"],
                point["index_name"], point["value"], point.get("price_change", 0), point["source"]))
        dates = sorted({str(event.get("date") or "") for event in events or [] if event.get("date")})
        previous = {}
        for date_text in dates:
            rows = c.execute("""SELECT s.code,s.direction,s.pool_state FROM limit_event_snapshots s
                JOIN (SELECT code,direction,MAX(id) AS id FROM limit_event_snapshots
                      WHERE date=? GROUP BY code,direction) latest ON latest.id=s.id""", (date_text,)).fetchall()
            previous.update({(date_text, row["direction"], row["code"]): row["pool_state"] for row in rows})
        for event in events or []:
            metadata = event.get("metadata", {}) or {}
            date_text = event["date"]
            direction = event.get("direction", "up")
            key = (date_text, direction, event["code"])
            pool_state = "opened" if event.get("final_state") in {"broken", "opened"} or event.get("state") in {"broken", "opened"} else "sealed"
            board_count = max(1, int(metadata.get("board_count") or 1))
            before = previous.get(key)
            if direction == "up":
                if before is None:
                    # A first observation seeds the known first-limit event.
                    _save_limit_transition(c, event, _pool_event_time(event, "first_limit_time", collected_at), "LIMIT_UP", collected_at)
                    if pool_state == "opened":
                        _save_limit_transition(c, event, _pool_event_time(event, "last_limit_time", collected_at), "BREAK", collected_at)
                    elif int(metadata.get("open_count") or 0) > 0:
                        # Historical pools disclose the number of intraday opens
                        # but not every timestamp. Record that fact without
                        # inventing a break time.
                        _save_limit_transition(c, event, _pool_event_time(event, "last_limit_time", collected_at), "REOPENED", collected_at)
                elif before != pool_state:
                    transition = "BREAK" if pool_state == "opened" else "RESEAL"
                    # The polling timestamp is the verified transition time.
                    _save_limit_transition(c, event, collected_at, transition, collected_at)
            c.execute("""INSERT OR REPLACE INTO limit_event_snapshots
                (date,observed_at,code,name,direction,pool_state,final_state,board,board_count,price_change,source,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (date_text, collected_at, event["code"], event["name"],
                direction, pool_state, event.get("final_state", ""), event.get("board", ""), board_count,
                event.get("price_change", 0), event.get("source", ""), json.dumps(metadata, ensure_ascii=False)))
            c.execute("""INSERT OR REPLACE INTO limit_events
                (date,event_time,collected_at,code,name,direction,state,final_state,price_change,board,logic_text,source,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (event["date"], event["event_time"], collected_at,
                event["code"], event["name"], event["direction"], event["state"], event["final_state"],
                event.get("price_change", 0), event.get("board", ""), event.get("logic_text", ""),
                event["source"], json.dumps(event.get("metadata", {}), ensure_ascii=False)))

def _pool_event_time(event, key, fallback):
    value = str((event.get("metadata", {}) or {}).get(key) or "")
    if len(value) == 5 and value[2] == ":":
        return f"{event['date']}T{value}:00"
    return fallback

def _save_limit_transition(conn, event, event_time, event_type, observed_at):
    metadata = dict(event.get("metadata", {}) or {})
    metadata["observed_at"] = observed_at
    conn.execute("""INSERT OR IGNORE INTO limit_event_transitions
        (date,event_time,code,name,direction,event_type,board,board_count,price_change,source,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (event["date"], event_time, event["code"], event["name"],
        event.get("direction", "up"), event_type, event.get("board", ""),
        max(1, int(metadata.get("board_count") or 1)), event.get("price_change", 0),
        event.get("source", ""), json.dumps(metadata, ensure_ascii=False)))

def market_timeline(date_text):
    init_db()
    with connect() as c:
        points = c.execute("""SELECT timestamp,index_code,index_name,value,price_change,source
            FROM market_index_points WHERE date=? ORDER BY timestamp""", (date_text,)).fetchall()
        events = c.execute("""SELECT event_time,code,name,direction,state,final_state,price_change,board,
            logic_text,source,metadata_json FROM limit_events WHERE date=? ORDER BY event_time""", (date_text,)).fetchall()
        transitions = c.execute("""SELECT event_time,code,name,direction,event_type,board,board_count,
            price_change,source,metadata_json FROM limit_event_transitions WHERE date=? ORDER BY event_time,id""", (date_text,)).fetchall()
    decoded_events = []
    for row in events:
        item = dict(row)
        item["board"] = normalize_board(item.get("board"))
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        decoded_events.append(item)
    decoded_transitions = []
    for row in transitions:
        item = dict(row)
        item["board"] = normalize_board(item.get("board"))
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        decoded_transitions.append(item)
    counts = {
        "up_limit": sum(item["final_state"] == "up_limit" for item in decoded_events),
        "down_limit": sum(item["final_state"] == "down_limit" for item in decoded_events),
        "broken": sum(item["final_state"] in {"broken", "opened"} for item in decoded_events),
    }
    point_items = [dict(row) for row in points]
    baseline = 0
    if point_items:
        first = point_items[0]
        change = float(first.get("price_change") or 0)
        baseline = round(float(first["value"]) / (1 + change / 100), 4) if change > -100 else float(first["value"])
    return {"date": date_text, "baseline": baseline, "indices": point_items, "events": decoded_events,
            "transitions": decoded_transitions, "counts": counts}

def get_report(date_text):
    init_db()
    with connect() as c:
        row = c.execute("SELECT * FROM daily_reports WHERE date=?", (date_text,)).fetchone()
    return dict(row) if row else None

def db_summary():
    init_db()
    with connect() as c:
        records = c.execute("SELECT COUNT(*) AS n FROM heat_records").fetchone()["n"]
        stocks = c.execute("SELECT COUNT(*) AS n FROM stocks").fetchone()["n"]
        latest_any = c.execute("SELECT MAX(timestamp) AS t FROM heat_records").fetchone()["t"]
        latest_real = c.execute("SELECT MAX(timestamp) AS t FROM heat_records WHERE json_extract(source_json,'$.provider') IN ('eastmoney+ths','eastmoney_history','ths_history','ths_fallback')").fetchone()["t"]
        days = c.execute("SELECT COUNT(DISTINCT substr(timestamp,1,10)) AS n FROM heat_records").fetchone()["n"]
        timeline_points = c.execute("SELECT COUNT(*) AS n FROM market_index_points").fetchone()["n"]
        limit_events = c.execute("SELECT COUNT(*) AS n FROM limit_events").fetchone()["n"]
    return {"records": records, "stocks": stocks, "history_days": days, "latest_timestamp": latest_real or latest_any, "latest_any_timestamp": latest_any, "timeline_points": timeline_points, "limit_events": limit_events}
