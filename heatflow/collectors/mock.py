from datetime import datetime
import random

STOCKS = [
    ("300308", "中际旭创", "AI算力"), ("688256", "寒武纪", "AI算力"), ("601138", "工业富联", "AI算力"),
    ("300502", "新易盛", "光模块"), ("002230", "科大讯飞", "人工智能"), ("601360", "三六零", "软件"),
    ("000977", "浪潮信息", "服务器"), ("300750", "宁德时代", "新能源"), ("002594", "比亚迪", "汽车"), ("688012", "中微公司", "半导体"),
    ("603019", "中科曙光", "算力"), ("601127", "赛力斯", "汽车"),
]

def collect(now=None):
    now = now or datetime.now()
    rng = random.Random(now.strftime("%Y%m%d%H%M"))
    values = []
    for i, (code, name, board) in enumerate(STOCKS):
        sources = {k: max(0, min(100, 72 - i * 3 + rng.uniform(-12, 12))) for k in ("ths", "eastmoney", "taoguba", "cls")}
        heat = sum(sources.values()) / len(sources)
        values.append({"timestamp": now.isoformat(timespec="seconds"), "code": code, "name": name, "board": board,
                       "heat_score": round(heat, 2), "price_change": round(rng.uniform(-4, 8), 2), "sources": sources})
    values.sort(key=lambda x: x["heat_score"], reverse=True)
    previous = {}
    for item in values:
        item["rank"] = values.index(item) + 1
        delta = item["heat_score"] - previous.get(item["code"], item["heat_score"] - rng.uniform(0, 5))
        item["delta_heat"] = round(delta, 2)
        item["final_score"] = round(0.7 * item["heat_score"] + 0.3 * delta, 2)
    return values
