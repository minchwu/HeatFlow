from ..db import recent_stock_history
from collections import Counter


def _related_titles(row, news_items, limit=2):
    matches = []
    for item in news_items:
        title = item.get("title", "")
        if row["name"] in title or (row.get("board") and row["board"] in title):
            matches.append(title)
    return matches[:limit]


def build_profiles(records, news_items=None):
    news_items = news_items or []
    profiles = []
    for row in records[:20]:
        history = recent_stock_history(row["code"], 80)
        active_history = [item for item in history if item.get("source_provider") in {"eastmoney+ths", "eastmoney_history", "ths_history", "ths_fallback"}]
        history = active_history or history
        daily = {}
        for item in history:
            daily.setdefault(item["timestamp"][:10], item)
        changes = [item.get("price_change", 0) for item in daily.values()]
        avg_abs = sum(abs(value) for value in changes) / len(changes) if changes else abs(row.get("price_change", 0))
        win_rate = sum(1 for value in changes if value > 0) / len(changes) if changes else 0
        top_count = sum(1 for item in history if item.get("rank", 99) <= 10)
        max_rise = max(changes or [row.get("price_change", 0)])
        tags = [row.get("board", "热点")]
        if avg_abs >= 4: tags.append("高弹性")
        if win_rate >= 0.6: tags.append("趋势股性")
        if max_rise >= 9: tags.append("涨停基因")
        if top_count >= 3: tags.append("反复活跃")
        if row.get("sources", {}).get("eastmoney_rank", 99) <= 10: tags.append("人气核心")
        related = _related_titles(row, news_items)
        sources = row.get("sources", {}); em_rank = sources.get("eastmoney_rank", 99); ths_index = sources.get("ths_index", 0)
        forum_score = max(sources.get("taoguba", 0), sources.get("cls", 0))
        if em_rank <= 10 and ths_index >= 6.5:
            signal = "人气排名与量价强度形成共振，属于当前辨识度较高的核心标的"
        elif ths_index >= 7 and em_rank > 10:
            signal = "同花顺量价强度先行，东方财富人气仍有提升空间，可观察是否形成补涨扩散"
        elif forum_score >= 2:
            signal = "论坛讨论开始升温，处于舆情发酵阶段，需等待行情确认"
        else:
            signal = "人气保持活跃，后续重点验证换手承接和题材持续性"
        logic = f"{row.get('board','市场热点')}：{signal}。东财人气第{em_rank}，同花顺强度{ths_index:.1f}，当日涨跌{row.get('price_change',0):+.2f}%。"
        if related: logic += " 讨论焦点：" + "；".join(related)
        character = f"近{max(len(changes),1)}个交易日样本胜率{win_rate*100:.0f}%，平均振幅代理{avg_abs:.1f}%；" + "、".join(tags[1:] or ["股性样本积累中"])
        profiles.append({
            "code": row["code"], "speculation_logic": logic, "stock_character": character,
            "tags": list(dict.fromkeys(tags)),
            "evidence": {"history_days": len(changes), "win_rate": round(win_rate * 100, 1), "avg_abs_change": round(avg_abs, 2), "top10_count": top_count, "related_titles": related},
        })
    return profiles


def build_market_insight(records, news_items=None):
    news_items = news_items or []; rows = records[:20]
    weights = Counter()
    for rank, row in enumerate(rows, 1): weights[row.get("board", "市场热点")] += max(1, 12 - rank)
    theme = weights.most_common(1)[0][0] if weights else "市场热点"
    leaders = [row for row in rows if row.get("board") == theme][:3] or rows[:3]
    leader_names = "、".join(row["name"] for row in leaders)
    platform_counts = Counter(item.get("source", "news") for item in news_items)
    platform_text = "、".join(f"{name}{count}条" for name, count in platform_counts.items()) or "公开讨论样本有限"
    core = f"核心逻辑集中在{theme}。{leader_names}同时具备较高人气辨识度，当前驱动来自人气榜排名、量价强度与公开讨论的共同验证；平台讨论样本为{platform_text}。"
    candidates = []
    for row in rows:
        sources = row.get("sources", {})
        if sources.get("ths_index", 0) >= 7 and sources.get("eastmoney_rank", 99) > 10:
            candidates.append(f"{row['name']}量价先行、人气排名仍有提升空间")
        elif max(sources.get("taoguba", 0), sources.get("cls", 0)) >= 2 and sources.get("eastmoney_rank", 99) > 8:
            candidates.append(f"{row['name']}讨论升温，关注行情是否确认")
        if len(candidates) >= 3: break
    opportunity = "；".join(candidates) if candidates else f"潜在机会主要观察{theme}内部从核心股向低位同逻辑标的扩散，确认条件是成交活跃度和人气排名同步上升。"
    return {"theme": theme, "core_logic": core, "opportunity": opportunity, "platform_counts": dict(platform_counts)}
