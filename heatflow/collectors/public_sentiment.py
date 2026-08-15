"""Public-page sentiment signals from Taoguba and CLS."""

from html.parser import HTMLParser
import re
from urllib.request import Request, urlopen

from ..config import load_config


def _clean(text): return re.sub(r"\s+", " ", str(text or "")).strip()


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_anchor = False; self.anchor_parts = []; self.titles = []; self.all_parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "a": self.in_anchor = True; self.anchor_parts = []
    def handle_endtag(self, tag):
        if tag == "a" and self.in_anchor:
            text = _clean("".join(self.anchor_parts))
            if 6 <= len(text) <= 120: self.titles.append(text)
            self.in_anchor = False
    def handle_data(self, data):
        text = _clean(data)
        if text:
            self.all_parts.append(text)
            if self.in_anchor: self.anchor_parts.append(text)


def _request(url, timeout):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HeatFlow/0.6", "Accept-Language": "zh-CN,zh;q=0.9", "Referer": url})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def _page_signal(source, url, rows, timeout):
    parser = _TextParser(); parser.feed(_request(url, timeout)); full_text = " ".join(parser.all_parts); scores = {}
    for row in rows:
        name_hits = full_text.count(row["name"]); code_hits = full_text.count(row["code"]); board = row.get("board", "")
        board_hits = full_text.count(board) if board not in ("主板", "创业板", "科创板", "北交所", "") else 0
        scores[row["code"]] = min(10, name_hits * 2.4 + code_hits * 1.2 + board_hits * 0.4)
    keywords = ("涨停", "热点", "主线", "算力", "芯片", "机器人", "人工智能", "新能源", "重组", "业绩", "消费", "医药")
    names = [row["name"] for row in rows]; items = []; seen = set()
    for title in parser.titles:
        if title in seen or not (any(name in title for name in names) or any(word in title for word in keywords)): continue
        seen.add(title); items.append({"source": source, "title": title, "url": url, "category": "public_web"})
        if len(items) >= 30: break
    return scores, items


def collect_sentiment(rows):
    cfg = load_config().get("collector", {}); timeout = int(cfg.get("timeout_seconds", 12))
    scores = {row["code"]: {"taoguba": 0, "cls": 0} for row in rows}; news_items = []; statuses = {}
    for source in ("taoguba", "cls", "sina", "wallstreetcn"):
        source_cfg = cfg.get(source, {})
        if not source_cfg.get("enabled", True): statuses[source] = ("disabled", "配置已关闭", 0); continue
        try:
            values, items = _page_signal(source, source_cfg.get("url"), rows, timeout)
            for code, score in values.items(): scores[code][source] = score
            news_items.extend(items)
            statuses[source] = (("ok", "公开页面舆情", len(items)) if items else ("limited", "页面可访问，但未提取到有效热点标题", 0))
        except Exception as exc: statuses[source] = ("error", str(exc), 0)
    return scores, news_items, statuses
