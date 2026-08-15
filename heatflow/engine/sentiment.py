def detect(records):
    if not records:
        return "暂无数据"
    rows = records[:10]
    avg_change = sum(r.get("price_change", 0) for r in rows) / len(rows)
    red_ratio = sum(r.get("price_change", 0) > 0 for r in rows) / len(rows) * 100
    strong_ratio = sum(r.get("price_change", 0) >= 5 for r in rows) / len(rows) * 100
    leader_change = rows[0].get("price_change", 0)
    if avg_change >= 4 or (red_ratio >= 80 and strong_ratio >= 50):
        return "高潮"
    if avg_change >= 2 or (red_ratio >= 70 and strong_ratio >= 30):
        return "发酵"
    if avg_change >= .5 and red_ratio >= 55:
        return "启动"
    if avg_change >= 0 and leader_change >= 2:
        return "修复"
    if avg_change >= -1:
        return "分歧"
    return "退潮"


def stage_tone(stage):
    return {
        "启动": "start", "发酵": "spread", "高潮": "climax",
        "分歧": "diverge", "修复": "repair", "退潮": "ebb",
    }.get(stage, "neutral")

def metrics(records):
    rows = records[:10]
    if not rows:
        return {"red_ratio": 0, "avg_change": 0, "heat_concentration": 0, "leader_change": 0}
    red = sum(1 for r in rows if r.get("price_change", 0) > 0)
    total_heat = sum(max(0, r.get("final_score", 0)) for r in rows) or 1
    return {
        "red_ratio": round(red / len(rows) * 100, 1),
        "avg_change": round(sum(r.get("price_change", 0) for r in rows) / len(rows), 2),
        "heat_concentration": round(max(0, rows[0].get("final_score", 0)) / total_heat * 100, 1),
        "leader_change": round(rows[0].get("price_change", 0), 2),
    }
