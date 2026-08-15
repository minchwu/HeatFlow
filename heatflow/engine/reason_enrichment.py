"""Multi-source, traceable enrichment for limit-up review reasons.

The output deliberately separates source-backed clues from taxonomy rules.
It is suitable for short-term review support, not for asserting a definitive
causal explanation for a stock's price move.
"""
from datetime import datetime

from .board_names import normalize_board


CONCEPT_RULES = (
    ("人工智能与算力", ("AI", "算力", "服务器", "通信", "软件", "计算机", "广告营销")),
    ("半导体与电子", ("半导体", "电子", "元件", "光学", "消费电子", "芯片", "存储")),
    ("高端制造与机器人", ("通用设备", "专用设备", "自动化", "工程机械", "轨交", "装备", "工业金属", "电网设备", "照明设备")),
    ("汽车产业链", ("汽车", "新能源车", "锂电")),
    ("医药健康", ("化学制药", "中药", "医药", "生物制品", "医疗")),
    ("基建地产", ("房地产", "基础建设", "装修装饰", "建筑")),
    ("化工材料", ("化学", "非金属材料", "塑料", "小金属", "纺织制造", "环境治理")),
    ("消费与食品", ("休闲食品", "非白酒", "家居", "家电", "消费", "调味")),
)

CATALYST_RULES = (
    ("政策催化", ("政策", "国务院", "会议", "规划", "补贴", "专项", "改革")),
    ("业绩与资本运作", ("业绩", "预增", "中报", "半年报", "年报", "重组", "回购", "并购", "增持")),
    ("产业与订单", ("订单", "中标", "合作", "发布", "量产", "投产", "扩产", "签约")),
    ("供需与价格", ("涨价", "供给", "缺货", "价格", "期货", "减产")),
    ("事件与情绪", ("涨停", "连板", "人气", "资金", "热点", "异动")),
)


def classify_concept(board):
    board = normalize_board(board)
    for name, keywords in CONCEPT_RULES:
        if any(keyword in board for keyword in keywords):
            return name
    return board or "其他题材"


def classify_catalyst(text):
    value = str(text or "")
    for name, keywords in CATALYST_RULES:
        if any(keyword in value for keyword in keywords):
            return name
    return "板块联动"


def _hhmm(value):
    text = str(value or "")
    import re
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?", text)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else "--:--"


def _belongs_to_session(news, date_text):
    """Never use an old headline as evidence for a later trading session."""
    stamp = str(news.get("published_at") or news.get("collected_at") or "")
    return stamp.startswith(str(date_text))


def build_reason_evidence(date_text, events, news_items, collected_at=None):
    """Return deduplicated per-stock evidence from quote-pool and public sources."""
    collected_at = collected_at or datetime.now().isoformat(timespec="seconds")
    output, seen = [], set()
    up_events = [event for event in events or [] if event.get("direction") == "up"]
    for event in up_events:
        code, name = str(event.get("code") or ""), str(event.get("name") or "")
        if not code:
            continue
        board = normalize_board(event.get("board")); concept = classify_concept(board)
        metadata = event.get("metadata") or {}
        raw_action = str(event.get("logic_text") or "资金封板确认").split("｜", 1)[-1]
        base = {
            "date": date_text, "code": code, "stock_name": name, "board": board,
            "concept": concept, "collected_at": collected_at,
        }
        pool_text = f"{board}｜{raw_action}；首次涨停 {_hhmm(metadata.get('first_limit_time') or event.get('event_time'))}"
        output.append({**base, "catalyst_type": "板块联动", "evidence_text": pool_text,
                       "source": "eastmoney_limit_pool", "source_url": "", "confidence": .46,
                       "metadata": {"kind": "quote_pool", "final_state": event.get("final_state", "")}})
        output.append({**base, "catalyst_type": "规则归类", "evidence_text": f"按行业映射归入{concept}，需结合公开资讯验证具体催化。",
                       "source": "heatflow_taxonomy", "source_url": "", "confidence": .32,
                       "metadata": {"kind": "rule", "board": board}})
        for news in news_items or []:
            if not _belongs_to_session(news, date_text):
                continue
            title = str(news.get("title") or "").strip()
            if not title:
                continue
            relevance = 0.0
            if name and name in title:
                relevance = 1.0
            elif code and code in title:
                relevance = .95
            elif board and board in title:
                relevance = .72
            elif any(keyword in title for concept_name, keywords in CONCEPT_RULES if concept_name == concept for keyword in keywords):
                relevance = .55
            if relevance < .55:
                continue
            key = (code, str(news.get("source") or "news"), title)
            if key in seen:
                continue
            seen.add(key)
            output.append({**base, "catalyst_type": classify_catalyst(title), "evidence_text": title,
                           "source": str(news.get("source") or "news"), "source_url": str(news.get("url") or ""),
                           "confidence": round(.36 + relevance * .46, 2),
                           "metadata": {"kind": "public_news", "published_at": news.get("published_at"), "category": news.get("category", "")}})
    return output
