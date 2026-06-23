from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urlparse


SOCIAL_SECURITY_TITLE_TERMS = (
    "社保",
    "社会保险",
    "养老保险",
    "职工基本养老保险",
    "医疗保险",
    "失业保险",
    "工伤保险",
    "缴费工资",
    "缴纳社会保险费",
)

BASE_LIMIT_TITLE_TERMS = (
    "缴费基数",
    "缴费工资基数",
    "基数上下限",
    "缴费基数上下限",
    "上限",
    "下限",
    "基准值",
    "计发基数",
)

ACTION_TITLE_TERMS = ("调整", "公布", "发布", "确定", "通告", "通知", "公告")

EXCLUDE_TERMS = (
    "住房公积金",
    "公积金缴存基数",
    "医保目录",
    "养老金待遇认证",
    "社保卡",
    "职业培训",
    "招聘公告",
    "财政预算",
)

AMOUNT_RE = re.compile(r"(?<!\d)(\d{3,6}(?:\.\d{1,2})?)\s*元(?:/月|每月)?")


def is_gov_cn_url(url: str) -> bool:
    """Return True when *url* belongs to gov.cn or any gov.cn subdomain."""

    try:
        hostname = urlparse(url).hostname or ""
    except ValueError:
        return False
    hostname = hostname.lower().rstrip(".")
    return hostname == "gov.cn" or hostname.endswith(".gov.cn")


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def has_excluded_topic(text: str) -> bool:
    return _contains_any(text or "", EXCLUDE_TERMS)


def is_candidate_title(title: str) -> bool:
    """Check whether a title may describe social-security base limits."""

    title = title or ""
    if not title or has_excluded_topic(title):
        return False
    return (
        _contains_any(title, SOCIAL_SECURITY_TITLE_TERMS)
        and _contains_any(title, BASE_LIMIT_TITLE_TERMS)
        and _contains_any(title, ACTION_TITLE_TERMS)
    )


def is_confirmed_social_security_limit_article(title: str, text: str) -> bool:
    """Confirm that article text is about social-security base upper/lower limits."""

    text = text or ""
    combined = f"{title or ''}\n{text}"
    if not is_candidate_title(title):
        return False
    if has_excluded_topic(combined):
        return False
    if "上限" not in text or "下限" not in text:
        return False
    if not AMOUNT_RE.search(text):
        return False
    return _contains_any(
        text,
        (
            "年度",
            "年7月1日",
            "年1月1日",
            "日起",
            "起执行",
            "缴费年度",
        ),
    )


def _year_from_date(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})", str(value))
    return int(match.group(1)) if match else None


def is_target_year_article(
    title: str, text: str, publish_date: str | None, target_year: int
) -> bool:
    """Return True when an article belongs to the requested target year."""

    target = str(target_year)
    if target in (title or "") or target in (text or ""):
        return True
    if ("本年度" in (text or "") or "当年度" in (text or "")) and (
        _year_from_date(publish_date) == target_year
    ):
        return True
    return False


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title or "")


def content_hash(text: str, limit: int | None = None) -> str:
    payload = (text or "")[:limit] if limit else (text or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def title_region_date_hash(region_code: str, title: str, publish_date: str | None) -> str:
    payload = f"{region_code or ''}|{normalize_title(title)}|{publish_date or ''}"
    return content_hash(payload)


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _date_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    match = re.search(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return text[:10]


def detect_update(new_record: dict[str, Any], existing_records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect whether *new_record* is new or changes prior region/year/type data."""

    matched = [
        item
        for item in existing_records
        if str(item.get("region_code") or "") == str(new_record.get("region_code") or "")
        and int(item.get("year") or 0) == int(new_record.get("year") or 0)
        and str(item.get("insurance_type") or "unknown")
        == str(new_record.get("insurance_type") or "unknown")
    ]

    base_event = {
        "region_code": new_record.get("region_code"),
        "region_name": new_record.get("region_name"),
        "year": new_record.get("year"),
        "insurance_type": new_record.get("insurance_type") or "unknown",
        "new_upper_limit": new_record.get("upper_limit"),
        "new_lower_limit": new_record.get("lower_limit"),
        "new_effective_start_date": new_record.get("effective_start_date"),
        "source_url": new_record.get("source_url"),
        "source_title": new_record.get("source_title"),
        "event_status": "pending",
    }

    if not matched:
        return {**base_event, "event_type": "new_record"}

    latest = matched[-1]
    event = {
        **base_event,
        "old_upper_limit": latest.get("upper_limit"),
        "old_lower_limit": latest.get("lower_limit"),
        "old_effective_start_date": latest.get("effective_start_date"),
    }
    if _to_decimal(latest.get("upper_limit")) != _to_decimal(new_record.get("upper_limit")) or _to_decimal(
        latest.get("lower_limit")
    ) != _to_decimal(new_record.get("lower_limit")):
        return {**event, "event_type": "value_changed"}

    if _date_value(latest.get("effective_start_date")) != _date_value(
        new_record.get("effective_start_date")
    ):
        return {**event, "event_type": "date_changed"}

    if latest.get("source_url") != new_record.get("source_url"):
        return {**event, "event_type": "source_updated"}
    return None


def should_initial_fetch(
    scope_type: str, scope_id: str, target_year: int, db: Any | None = None
) -> bool:
    """Return whether the scope has no successful init state for target_year."""

    if db is None:
        from .storage import default_db

        db = default_db()
    row = db.fetchone(
        """
        SELECT init_status
        FROM crawler_init_state
        WHERE scope_type = ? AND scope_id = ? AND target_year = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (scope_type, scope_id, target_year),
    )
    return row is None or row["init_status"] != "success"


def get_crawler_run_mode(
    scope_type: str, scope_id: str, target_year: int, db: Any | None = None
) -> str:
    return (
        "initial_fetch"
        if should_initial_fetch(scope_type, scope_id, target_year, db=db)
        else "daily_monitor"
    )
