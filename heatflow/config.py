from pathlib import Path
import os
import yaml

ROOT = Path(__file__).resolve().parent
APP_VERSION = "1.6.0"
# v1.0 is self-contained: runtime data and visual assets live beside the
# release package, while environment variables remain available for external
# deployments or shared storage.
RELEASE_DIR = ROOT.parent
DATA_DIR = Path(os.environ.get("HEATFLOW_DATA_DIR", RELEASE_DIR / ".heatflow-live"))
STATIC_DIR = Path(os.environ.get("HEATFLOW_STATIC_DIR", RELEASE_DIR / ".heatflow-assets"))
CONFIG_PATH = ROOT.parent / "config.yaml"

def load_config():
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def ensure_dirs():
    for name in ("reports", "logs"):
        (DATA_DIR / name).mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
