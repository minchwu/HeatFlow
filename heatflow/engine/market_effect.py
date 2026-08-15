from datetime import datetime


def evaluate(records, timestamp=None, breadth=None):
    timestamp = timestamp or datetime.now()
    rows = list(records)
    breadth = breadth if breadth and breadth.get("sample_size", 0) else None
    count = int(breadth.get("sample_size", 0)) if breadth else len(rows)
    if not count:
        return {"timestamp": timestamp.isoformat(timespec="seconds"), "date": timestamp.strftime("%Y-%m-%d"), "sample_size": 0, "red_ratio": 0, "avg_change": 0, "strong_ratio": 0, "weak_ratio": 0, "heat_concentration": 0, "label": "暂无数据", "tone": "neutral", "summary": "暂无足够样本判断市场状态。", "data_scope": "无"}
    if breadth:
        count = int(breadth.get("sample_size", 0))
        red_ratio = float(breadth.get("red_ratio", 0))
        strong_ratio = float(breadth.get("strong_ratio", 0))
        weak_ratio = float(breadth.get("weak_ratio", 0))
        avg_change = float(breadth.get("avg_change", 0))
    else:
        changes = [row.get("price_change", 0) for row in rows]
        red_ratio = sum(value > 0 for value in changes) / count * 100
        strong_ratio = sum(value >= 5 for value in changes) / count * 100
        weak_ratio = sum(value <= -5 for value in changes) / count * 100
        avg_change = sum(changes) / count
    heats = sorted((max(0, row.get("final_score", 0)) for row in rows), reverse=True)
    concentration = sum(heats[:5]) / (sum(heats) or 1) * 100
    if red_ratio >= 70 and avg_change >= 2:
        label, tone = "情绪高涨，强势扩散", "hot"
    elif red_ratio >= 55 and avg_change >= 0.5:
        label, tone = "情绪偏暖，机会较多", "warm"
    elif red_ratio <= 35 or avg_change <= -2:
        label, tone = "情绪冰冷，亏损扩散", "cold"
    elif red_ratio <= 45 or avg_change < -0.5:
        label, tone = "情绪偏冷，谨慎为主", "cool"
    else:
        label, tone = "多空分化，结构轮动", "neutral"
    if breadth:
        summary = (f"全市场上涨{int(breadth.get('up_count', 0))}家、下跌{int(breadth.get('down_count', 0))}家、平盘{int(breadth.get('flat_count', 0))}家；"
                   f"红盘率{red_ratio:.0f}%，平均涨跌{avg_change:+.2f}%，强势股占比{strong_ratio:.0f}%，弱势股占比{weak_ratio:.0f}%；{label}。")
    else:
        summary = f"红盘率{red_ratio:.0f}%，平均涨跌{avg_change:+.2f}%，强势股占比{strong_ratio:.0f}%，弱势股占比{weak_ratio:.0f}%；{label}。"
    scope = f"东方财富全市场A股（{count}只）" if breadth else f"东方财富与同花顺热股样本（{count}只）"
    return {"timestamp": timestamp.isoformat(timespec="seconds"), "date": timestamp.strftime("%Y-%m-%d"), "sample_size": count, "red_ratio": round(red_ratio, 1), "avg_change": round(avg_change, 2), "strong_ratio": round(strong_ratio, 1), "weak_ratio": round(weak_ratio, 1), "heat_concentration": round(concentration, 1), "label": label, "tone": tone, "summary": summary, "data_scope": scope}


def media_copy(records, theme, sentiment, effect, topics=None, insight=None):
    topics = topics or []
    names = "、".join(row["name"] for row in records[:3]) or "暂无热度样本"
    topic_text = "；".join(item.get("title", "") for item in topics[:3]) or f"资金继续围绕{theme}寻找辨识度"
    insight = insight or {}
    core_logic = insight.get("core_logic", f"{theme}方向保持活跃，等待资金进一步确认。")
    opportunity = insight.get("opportunity", f"观察{theme}核心股能否继续放量，以及同逻辑低位标的是否形成扩散。")
    risk = insight.get("risk", "若成交额、涨停家数和板块扩散同步回落，需警惕高位分歧向退潮传导。")
    leaders = "、".join(row["name"] for row in records[:5]) or "暂无"
    return (f"【收盘复盘｜邻小路】\n\n"
            f"今天市场处于{sentiment}阶段。{effect.get('summary', '全市场数据暂不可用')}\n\n"
            f"主线与结构：{core_logic} 当前热度靠前的代表股包括{leaders}，但热度排名不等同于趋势确认，仍要结合成交、封板质量与板块扩散判断。\n\n"
            f"舆论与催化：{topic_text}。这些讨论若能转化为成交额放大和同题材梯队补涨，主线才具备持续性；若只停留在单一龙头，更多是局部交易机会。\n\n"
            f"明日观察：{opportunity} 重点观察红盘率、平均涨跌、涨跌停结构是否继续改善，以及核心股与后排之间的强弱差。\n\n"
            f"风险提示：{risk}\n\n"
            "以上内容为基于公开行情与舆情的收盘复盘，不构成投资建议。关注邻小路，每天收盘梳理市场。\n\n"
            "#A股 #股市复盘 #赚钱效应 #热点题材 #邻小路")
