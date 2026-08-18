import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get(
        "DASHBOARD_SECRET_KEY",
        "MP20_CHANGE_THIS_SECRET_KEY",
    )
    DB_PATH = os.environ.get(
        "DASHBOARD_DB_PATH",
        str(BASE_DIR / "data" / "robot_dashboard.db"),
    )
