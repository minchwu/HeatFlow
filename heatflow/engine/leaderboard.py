from collections import Counter

def top10(records):
    rows = [dict(r) for r in sorted(records, key=lambda x: x.get("final_score", x["heat_score"]), reverse=True)[:10]]
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return rows

def board_share(records):
    c = Counter(r.get("board", "其他") for r in top10(records))
    total = sum(c.values()) or 1
    return [{"board": k, "count": v, "share": round(v / total * 100, 1)} for k, v in c.most_common()]

def main_theme(records):
    shares = board_share(records)
    return shares[0]["board"] if shares else "暂无主线"

def leader_tiers(records):
    rows = top10(records)
    if not rows:
        return {}
    # MVP heuristic: these roles are explainable and can later be replaced by richer market data.
    capacity = max(rows, key=lambda r: r.get("heat_score", 0))
    return {
        "空间龙": rows[0],
        "情绪龙": rows[1] if len(rows) > 1 else rows[0],
        "容量龙": capacity,
        "趋势龙": max(rows, key=lambda r: r.get("price_change", 0)),
        "补涨龙": rows[-1],
    }
