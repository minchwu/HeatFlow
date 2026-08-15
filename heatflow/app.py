import argparse
from .config import load_config, ensure_dirs
from .db import init_db
from .scheduler.jobs import run_once, run_schedule, backfill_week
from .web.routes import create_app

def main():
    p = argparse.ArgumentParser(description="HeatFlow MVP")
    p.add_argument("--once", action="store_true", help="采集一次并生成日报")
    p.add_argument("--web", action="store_true", help="启动 Dashboard")
    p.add_argument("--schedule", action="store_true", help="交易时段循环采集")
    p.add_argument("--backfill", action="store_true", help="补齐近一周真实历史数据")
    p.add_argument("--bootstrap", action="store_true", help="补齐历史并采集一次")
    args = p.parse_args(); ensure_dirs(); init_db()
    if args.once:
        result = run_once(); print(f"已生成：{result['report']}")
    elif args.backfill:
        result = backfill_week(); print(f"已补齐：{result['days']} 个交易日，{result['records']} 条记录")
    elif args.bootstrap:
        history = backfill_week(); current = run_once()
        print(f"初始化完成：{history['days']} 个交易日；日报：{current['report']}")
    elif args.schedule: run_schedule()
    else:
        cfg = load_config().get("app", {}); create_app().run(host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 5000)), debug=False)

if __name__ == "__main__": main()
