from __future__ import annotations

from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def configured_timezone() -> ZoneInfo:
    name = os.getenv("APP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def timezone_name() -> str:
    return str(configured_timezone().key)


def local_today_iso() -> str:
    return datetime.now(configured_timezone()).date().isoformat()


def normalize_utc_datetime(value: str) -> str:
    """Normalize a UI/API timestamp to UTC; naive values use APP_TIMEZONE."""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=configured_timezone())
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
