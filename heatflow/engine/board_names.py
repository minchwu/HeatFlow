"""Canonical sector labels used by live and historical limit-event data."""

BOARD_NAME_FIXES = {
    "汽车零部": "汽车零部件", "房地产开": "房地产开发", "自动化设": "自动化设备",
    "计算机应": "计算机应用", "计算机设": "计算机设备", "专用设": "专用设备", "通用设": "通用设备",
    "环保设": "环保设备", "化学制": "化学制品", "包装印": "包装印刷",
    "通信设": "通信设备", "电子化": "电子化学品", "家居用": "家居用品",
    "服装家": "服装家纺", "工程咨": "工程咨询", "塑料": "塑料制品",
    # Eastmoney's limit-pool endpoint sometimes cuts the final character(s)
    # from industry labels. Keep these canonical forms shared by live,
    # historical, tower and homepage data.
    "非金属材": "非金属材料", "家电零部": "家电零部件",
    "炼化及贸": "炼化及贸易", "电子化学": "电子化学品",
}


def normalize_board(value):
    text = str(value or "").strip()
    return BOARD_NAME_FIXES.get(text, text or "市场热点")
