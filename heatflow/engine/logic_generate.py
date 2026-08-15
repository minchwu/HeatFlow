def generate(records, theme, sentiment):
    names = "、".join(r["name"] for r in records[:3])
    return f"{theme}方向热度居前，{names}获资金与资讯集中关注。当前处于{sentiment}，建议继续观察量价配合及板块内部扩散。"

def douyin_copy(records, theme, sentiment):
    names = "、".join(r["name"] for r in records[:3])
    return (f"今日A股热度TOP10出炉。\n\n真正的主线仍是{theme}。\n\n{names}持续位居热度前列。\n\n"
            f"一句话总结：市场情绪处于{sentiment}，主线仍需看持续性。\n\n"
            "明天重点关注：主线龙头能否继续放量、热点能否扩散。\n\n"
            "关注我，每天15:10看懂市场热点。\n\n#A股 #股市热点 #投资复盘")
