from ..config import load_config
from ..db import latest_collector_runs

def source_status():
    cfg = load_config().get("collector", {})
    mode = cfg.get("mode", "mock")
    latest = {row["source"]: row for row in latest_collector_runs()}
    output = []
    for name in cfg.get("sources", []):
        run = latest.get(name)
        if run:
            output.append({"name": name, "mode": mode, "status": run["status"], "records": run["record_count"], "checked_at": run["run_at"], "message": run.get("message", "")})
        else:
            output.append({"name": name, "mode": mode, "status": "waiting", "records": 0, "checked_at": None, "message": "尚未执行采集"})
    return output
