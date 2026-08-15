"""Concept-oriented review of the day's limit-up events.

Eastmoney's limit-pool feed provides a sector and a state, but its reason
field is often a short action label.  This module keeps the raw reason and
adds a deterministic concept classification so the review remains useful
when news enrichment is unavailable.
"""
from collections import Counter, defaultdict

from ..engine.board_names import normalize_board
from ..db import market_timeline, limit_reason_evidence_for_date, latest_news
from .reason_enrichment import classify_concept, build_reason_evidence


CONCEPT_EXPLANATIONS = {
    "人工智能与算力": "围绕算力基础设施、软件应用与通信链条扩散，重点观察前排连板的承接与后排补涨。",
    "半导体与电子": "资金围绕芯片、元件和消费电子方向做强，涨停持续性取决于板块梯队与成交放大。",
    "高端制造与机器人": "高端制造链出现资金聚集，关注连板高度能否带动同方向首板扩散。",
    "汽车产业链": "汽车产业链的交易重点在核心标的强度与零部件补涨的持续性。",
    "医药健康": "医药方向以事件催化和防御属性为主，需区分单点脉冲与板块共振。",
    "基建地产": "基建地产方向更依赖政策预期与权重联动，观察涨停数量和封板质量是否同步改善。",
    "化工材料": "材料方向的上涨通常体现供需、价格或政策线索，关注同逻辑个股的扩散效率。",
    "消费与食品": "消费方向偏事件与景气驱动，短线参与优先选择板块内封板时间靠前的标的。",
}


def _hhmm(value, fallback="--:--"):
    """Normalize ISO timestamps and existing HH:MM metadata to HH:MM."""
    text = str(value or "")
    import re
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return fallback
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _concept(board):
    board = normalize_board(board)
    concept = classify_concept(board)
    return concept, CONCEPT_EXPLANATIONS.get(concept, "暂未匹配到明确的共性概念，需结合盘口、公告与当日舆情进一步确认。")


def _event(item):
    metadata = item.get("metadata") or {}
    board = normalize_board(item.get("board"))
    concept, concept_reason = _concept(board)
    height = max(1, int(metadata.get("board_count") or 1))
    final_state = item.get("final_state") or item.get("state") or "up_limit"
    broken = final_state in {"broken", "opened"} or item.get("state") in {"broken", "opened"}
    first = _hhmm(metadata.get("first_limit_time") or item.get("event_time"))
    last = _hhmm(metadata.get("last_limit_time") or item.get("event_time"))
    action = "炸板" if broken else (f"{height}连板封板" if height > 1 else "首板封板")
    raw_logic = str(item.get("logic_text") or "").split("｜", 1)[-1]
    return {
        "code": str(item.get("code") or ""), "name": str(item.get("name") or item.get("code") or "未知个股"),
        "board": board, "concept": concept, "concept_reason": concept_reason,
        "height": height, "event_time": _hhmm(item.get("event_time")),
        "first_limit_time": first, "last_limit_time": last,
        "state": "炸板" if broken else "涨停", "broken": broken,
        "price_change": float(item.get("price_change") or 0),
        "reason": f"{concept}｜{board}{action}；{raw_logic or concept_reason}",
    }


def build_limit_review(date_text):
    timeline = market_timeline(date_text)
    events = [_event(item) for item in timeline.get("events", []) if item.get("direction") == "up"]
    evidence_rows = limit_reason_evidence_for_date(date_text)
    if not evidence_rows:
        # The first view remains useful before the scheduler has persisted a
        # run: enrich from the locally cached public-source news, but label it
        # as evidence rather than a certain causal claim.
        evidence_rows = build_reason_evidence(date_text, timeline.get("events", []), latest_news(80))
    evidence_by_code = defaultdict(list)
    for evidence in evidence_rows:
        evidence_by_code[str(evidence.get("code") or "")].append(evidence)
    for item in events:
        evidence = sorted(evidence_by_code.get(item["code"], []), key=lambda row: float(row.get("confidence") or 0), reverse=True)
        external = [row for row in evidence if row.get("source") not in {"eastmoney_limit_pool", "heatflow_taxonomy"}]
        primary = (external or evidence or [{}])[0]
        item["evidence"] = evidence[:3]
        item["confidence"] = round(float(primary.get("confidence") or 0), 2)
        item["confidence_label"] = "多源佐证" if len({row.get("source") for row in external}) >= 2 else ("公开线索" if external else "板块推断")
        item["evidence_sources"] = list(dict.fromkeys(str(row.get("source") or "") for row in evidence if row.get("source")))
        if primary.get("evidence_text"):
            item["reason"] = f"{primary.get('catalyst_type','板块联动')}｜{primary['evidence_text']}"
    groups = defaultdict(list)
    for item in events:
        groups[item["concept"]].append(item)
    concepts = []
    for concept, items in groups.items():
        items.sort(key=lambda item: (-item["height"], item["event_time"], item["name"]))
        concepts.append({
            "concept": concept,
            "count": len(items),
            "highest_height": max(item["height"] for item in items),
            "first_time": min(item["event_time"] for item in items),
            "reason": items[0]["concept_reason"],
            "items": items,
        })
    concepts.sort(key=lambda item: (-item["highest_height"], -item["count"], item["first_time"], item["concept"]))
    sealed = sum(not item["broken"] for item in events)
    broken = sum(item["broken"] for item in events)
    heights = Counter(item["height"] for item in events if not item["broken"])
    source_counts = Counter(str(row.get("source") or "unknown") for row in evidence_rows)
    external_sources = [source for source in source_counts if source not in {"eastmoney_limit_pool", "heatflow_taxonomy"}]
    return {
        "date": date_text,
        "events": events,
        "concepts": concepts,
        "summary": {"total": len(events), "sealed": sealed, "broken": broken,
                     "highest_height": max((item["height"] for item in events), default=0),
                     "first_board": heights.get(1, 0),
                     "continuation": sum(count for height, count in heights.items() if height >= 2)},
        "reason_evidence": {"total": len(evidence_rows), "sources": dict(source_counts),
                            "external_sources": external_sources,
                            "mode": "多源证据" if external_sources else "行情池 + 规则归类"},
        "generated_at": timeline.get("generated_at"),
    }
