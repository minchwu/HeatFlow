import csv, json
from pathlib import Path
from ..config import DATA_DIR
from ..db import save_report

def export_report(date_text, records, theme, sentiment, logic, copy, sentiment_metrics=None, leaders=None, market_effect=None, topics=None, profiles=None):
    folder = DATA_DIR / "reports" / date_text
    folder.mkdir(parents=True, exist_ok=True)
    top = records[:10]
    (folder / "douyin_copy.txt").write_text(copy, encoding="utf-8")
    (folder / "sentiment.json").write_text(json.dumps({"date": date_text, "stage": sentiment, "main_theme": theme}, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps(sentiment_metrics or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "leaders.json").write_text(json.dumps(leaders or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "market_effect.json").write_text(json.dumps(market_effect or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "hot_topics.json").write_text(json.dumps(topics or [], ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "stock_profiles.json").write_text(json.dumps(profiles or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (folder / "top10.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "code", "name", "board", "final_score", "price_change"], extrasaction="ignore"); w.writeheader(); w.writerows(top)
    leader_lines = "\n".join(f"- {k}：{v.get('name', '')}（{v.get('board', '')}）" for k, v in (leaders or {}).items())
    profile_lines = "\n".join(f"- {r['name']}：{(profiles or {}).get(r['code'],{}).get('speculation_logic','画像积累中')}｜股性：{(profiles or {}).get(r['code'],{}).get('stock_character','样本积累中')}" for r in top)
    topic_lines = "\n".join(f"- [{item.get('source','news')}] {item.get('title','')}" for item in (topics or [])[:10]) or "- 暂无公开舆情标题"
    md = f"# HeatFlow {date_text}\n\n- 主线板块：{theme}\n- 情绪阶段：{sentiment}\n- 赚钱效应：{(market_effect or {}).get('label','暂无')}\n- 数据范围：{(market_effect or {}).get('data_scope','暂无')}\n\n## 赚钱效应总结\n\n{(market_effect or {}).get('summary','暂无')}\n\n## 情绪指标\n\n```json\n{json.dumps(sentiment_metrics or {}, ensure_ascii=False, indent=2)}\n```\n\n## 龙头梯队\n\n{leader_lines}\n\n## 当天舆论热点\n\n{topic_lines}\n\n## 炒作逻辑\n\n{logic}\n\n### 个股画像\n\n{profile_lines}\n\n## Top10\n\n" + "\n".join(f"{r['rank']}. {r['name']}（{r['board']}）— {r['final_score']:.1f}" for r in top) + f"\n\n## 自媒体文案\n\n{copy}\n"
    (folder / "report.md").write_text(md, encoding="utf-8")
    html = "<html><meta charset='utf-8'><body><pre>" + md.replace("&", "&amp;").replace("<", "&lt;") + "</pre></body></html>"
    (folder / "report.html").write_text(html, encoding="utf-8")
    save_report({"date": date_text, "top10": top, "main_theme": theme, "sentiment_stage": sentiment, "logic_text": logic, "douyin_copy": copy, "market_effect": market_effect or {}})
    return folder
