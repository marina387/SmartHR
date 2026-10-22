"""Единая временная зона пользовательского интерфейса."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def local_now():
    return datetime.now(ZoneInfo(os.getenv("SMARTHR_TIMEZONE", "Asia/Yekaterinburg")))
