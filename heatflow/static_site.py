"""Build a frozen, privacy-safe GitHub Pages snapshot from local HeatFlow data.

The public site contains rendered pages and JSON snapshots only.  The local
SQLite database, collector logs and runtime paths never leave ``.heatflow-live``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from .config import APP_VERSION, RELEASE_DIR, STATIC_DIR
from .db import available_history_dates, available_tower_dates, records_for_date


REAL_PROVIDERS = {"eastmoney+ths", "eastmoney_history", "ths_history", "ths_fallback"}
STATIC_ROOT = RELEASE_DIR / "site"


def _json(client, path: str):
    response = client.get(path)
    if response.status_code != 200:
        raise RuntimeError(f"静态导出接口异常：{path} ({response.status_code})")
    return response.get_json()


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _rewrite_shared_urls(html: str, depth: int) -> str:
    """Turn Flask absolute links into project-relative GitHub Pages links."""
    root = "../" if depth else "./"
    assets = "../assets/" if depth else "assets/"
    links = {
        'href="/tower"': f'href="{root}tower/"',
        'href="/limit-review"': f'href="{root}limit-review/"',
        'href="/history"': f'href="{root}history/"',
        'href="/"': f'href="{root}"',
        'href="/api/health"': 'href="https://github.com/minchwu/HeatFlow"',
    }
    for old, new in links.items():
        html = html.replace(old, new)
    html = re.sub(r'href="/favicon\.ico(?:\?[^\"]*)?"', f'href="{assets}youtianxia-favicon.png"', html)
    html = re.sub(r'src="/static/([^\"?]+)(?:\?[^\"]*)?"', lambda m: f'src="{assets}{m.group(1)}"', html)
    return html


def _only_snapshot_option(html: str, select_id: str, date_text: str) -> str:
    pattern = rf'(<select id="{re.escape(select_id)}"[^>]*>).*?(</select>)'
    option = f'<option value="{date_text}" selected>{date_text}</option>'
    return re.sub(pattern, lambda match: match.group(1) + option + match.group(2), html, flags=re.S)


def _freeze_html(html: str, page: str, date_text: str) -> str:
    """Disable live polling and repoint manual lookups to exported JSON."""
    html = _rewrite_shared_urls(html, 0 if page == "index" else 1)
    frozen = (
        '<script>window.HEATFLOW_STATIC=true;</script>'
        '<style>.static-freeze{position:sticky;top:0;z-index:99;padding:8px 16px;'
        'text-align:center;background:#102b45;color:#9fdcff;border-bottom:1px solid #2f6b92;'
        'font:12px Consolas,"Microsoft Yahei",sans-serif;letter-spacing:.4px}</style>'
    )
    html = html.replace("</head>", frozen + "</head>", 1)
    html = html.replace("<body>", f'<body><div class="static-freeze">收盘静态复盘 · {date_text} · 数据冻结，非实时行情</div>', 1)
    if page == "tower":
        html = _only_snapshot_option(html, "quick-day", date_text)
        # The replay payload is several megabytes.  Keep it in a separately
        # cacheable JSON file rather than embedding it a second time in HTML.
        html = re.sub(
            r"let tower=.*?,frameIndex=0,playing=false,timer=null,speed=1,newsItems=\[\];",
            "let tower={frames:[]},frameIndex=0,playing=false,timer=null,speed=1,newsItems=[];",
            html, count=1, flags=re.S,
        )
        html = html.replace(
            "fetch('/api/tower/'+encodeURIComponent(dateText),{cache:'no-store'})",
            "fetch('../data/tower/'+encodeURIComponent(dateText)+'.json')",
        )
        html = html.replace("fetch('/api/hot-news'", "fetch('../data/hot-news.json'")
        html = html.replace(
            "render();loadNews();",
            f"loadTower('{date_text}').then(loadNews).catch(()=>{{$('distribution').innerHTML='<div class=\"empty\">静态回放数据加载失败</div>'}});",
            1,
        )
    elif page == "limit-review":
        html = _only_snapshot_option(html, "date", date_text)
        html = re.sub(
            r"const initial=.*?,date=document\.getElementById\('date'\);",
            "const initial=null,date=document.getElementById('date');",
            html, count=1, flags=re.S,
        )
        html = html.replace(
            "fetch('/api/limit-review/'+encodeURIComponent(date.value),{cache:'no-store'})",
            "fetch('../data/limit-review/'+encodeURIComponent(date.value)+'.json')",
        )
        html = html.replace(
            "render(initial);",
            f"fetch('../data/limit-review/{date_text}.json').then(r=>r.json()).then(render).catch(()=>{{document.getElementById('concepts').innerHTML='<div class=\"empty\">静态复盘数据加载失败</div>'}});",
            1,
        )
    elif page == "history":
        html = html.replace("fetch('/history/'+d)", "fetch('../data/history/'+d+'.json')")
        html = html.replace("fetch('/api/history/dates'", "fetch('../data/history/dates.json'")
    return html


def _assert_publishable(date_text: str, require_real: bool):
    rows = records_for_date(date_text)
    if not rows:
        raise RuntimeError(f"{date_text} 没有热股记录，拒绝生成空白公开站点。")
    if require_real and not any(row.get("source_provider") in REAL_PROVIDERS for row in rows):
        raise RuntimeError(f"{date_text} 没有可验证的真实行情记录，拒绝发布模拟数据。")


def export_static_site(date_text: str | None = None, output: Path | None = None, require_real: bool = True):
    """Render the latest completed session as a GitHub Pages-ready ``site/`` tree."""
    # Import after disabling the internal collector: exporting must only read
    # the settled database snapshot, never start a competing scraper thread.
    os.environ["HEATFLOW_DISABLE_BACKGROUND"] = "1"
    from .web.routes import create_app

    tower_dates = [item["date"] for item in available_tower_dates(30)]
    if not tower_dates:
        raise RuntimeError("未找到涨停事件数据，暂不能生成收盘静态站点。")
    date_text = date_text or tower_dates[0]
    if date_text not in tower_dates:
        raise RuntimeError(f"{date_text} 没有完整涨停事件数据，拒绝发布不完整复盘。")
    _assert_publishable(date_text, require_real)
    target = Path(output or STATIC_ROOT).resolve()
    project_root = RELEASE_DIR.resolve()
    if target != (project_root / "site").resolve():
        raise ValueError("静态发布目录必须是项目根目录下的 site。");

    app = create_app()
    client = app.test_client()
    index_payload = _json(client, "/api/latest")
    if index_payload.get("market_date") != date_text:
        raise RuntimeError(f"热股快照日期 {index_payload.get('market_date')} 与涨停复盘日期 {date_text} 不一致，拒绝发布。")
    hot_news = _json(client, "/api/hot-news")
    timeline = _json(client, f"/api/market-timeline/{date_text}")
    tower = _json(client, f"/api/tower/{date_text}")
    review = _json(client, f"/api/limit-review/{date_text}")
    history_dates = available_history_dates(7)
    history_payloads = {item["date"]: _json(client, f"/history/{item['date']}") for item in history_dates}
    pages = {
        "index": client.get("/").get_data(as_text=True),
        "tower": client.get("/tower").get_data(as_text=True),
        "limit-review": client.get("/limit-review").get_data(as_text=True),
        "history": client.get("/history").get_data(as_text=True),
    }
    staging = project_root / ".site-build"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        assets = staging / "assets"; assets.mkdir()
        for source_name in ("youtianxia-logo.png", "youtianxia-favicon.png"):
            source = STATIC_DIR / source_name
            if not source.exists() and source_name == "youtianxia-favicon.png":
                source = STATIC_DIR / "youtianxia-logo.png"
            if not source.exists():
                raise RuntimeError(f"缺少静态品牌资产：{source_name}")
            shutil.copy2(source, assets / source_name)
        (staging / "index.html").write_text(_freeze_html(pages["index"], "index", date_text), encoding="utf-8")
        for name in ("tower", "limit-review", "history"):
            folder = staging / name; folder.mkdir()
            (folder / "index.html").write_text(_freeze_html(pages[name], name, date_text), encoding="utf-8")
        _write_json(staging / "data" / "latest.json", index_payload)
        _write_json(staging / "data" / "hot-news.json", hot_news)
        _write_json(staging / "data" / "timeline" / f"{date_text}.json", timeline)
        _write_json(staging / "data" / "tower" / f"{date_text}.json", tower)
        _write_json(staging / "data" / "limit-review" / f"{date_text}.json", review)
        _write_json(staging / "data" / "history" / "dates.json", {"dates": history_dates, "overview": _json(client, "/api/history/dates").get("overview", [])})
        for day, payload in history_payloads.items():
            _write_json(staging / "data" / "history" / f"{day}.json", payload)
        manifest = {
            "version": APP_VERSION,
            "market_date": date_text,
            "generated_at": max(row["timestamp"] for row in records_for_date(date_text)),
            "mode": "收盘静态复盘",
            "notice": "公开站点不包含本地 SQLite、日志或实时采集接口。",
        }
        _write_json(staging / "manifest.json", manifest)
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Export a frozen HeatFlow snapshot for GitHub Pages")
    parser.add_argument("--date", help="交易日，例如 2026-08-14；默认最新完整涨停复盘日")
    parser.add_argument("--allow-sample", action="store_true", help="仅用于本地预览；允许模拟行情导出")
    args = parser.parse_args()
    result = export_static_site(args.date, require_real=not args.allow_sample)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
