from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .rules import is_candidate_title, is_gov_cn_url


INSURANCE_TYPE_MAP = {
    "职工基本养老保险": "pension",
    "机关事业单位养老保险": "pension",
    "基本养老保险": "pension",
    "养老保险": "pension",
    "养老": "pension",
    "职工基本医疗保险": "medical",
    "基本医疗保险": "medical",
    "医疗保险": "medical",
    "医疗": "medical",
    "失业保险": "unemployment",
    "失业": "unemployment",
    "工伤保险": "work_injury",
    "工伤": "work_injury",
    "生育保险": "maternity",
    "生育": "maternity",
}

REGION_HINTS = {
    "rsj.sh.gov.cn": ("310000", "上海市", "上海市", None, None),
    "sh.gov.cn": ("310000", "上海市", "上海市", None, None),
    "hrss.zs.gov.cn": ("442000", "中山市", "广东省", "中山市", None),
    "zs.gov.cn": ("442000", "中山市", "广东省", "中山市", None),
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；;])|\n+")
DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
MONTH_RE = re.compile(r"(20\d{2})年(\d{1,2})月(?:起|开始|执行)?")
YEAR_RE = re.compile(r"(20\d{2})\s*年(?:度)?")
MONEY_RE = re.compile(r"(?<!\d)(\d{3,6}(?:\.\d{1,2})?)\s*元(?:/月|每月)?")


def _money(value: str | None) -> Decimal | None:
    return Decimal(value).quantize(Decimal("0.01")) if value else None


def _find_money(label: str, text: str) -> Decimal | None:
    escaped = re.escape(label)
    change = re.search(
        escaped + r"[^。；;，,\n]{0,24}?由\s*\d{3,6}(?:\.\d{1,2})?\s*元?[^。；;，,\n]{0,16}?调整为\s*(\d{3,6}(?:\.\d{1,2})?)\s*元",
        text,
    )
    if change:
        return _money(change.group(1))
    generic = re.search(
        escaped + r"[^。；;，,\n]{0,28}?(?:调整为|确定为|为|至|执行)\s*(\d{3,6}(?:\.\d{1,2})?)\s*元",
        text,
    )
    if generic:
        return _money(generic.group(1))
    return None


def _extract_upper_lower(segment: str) -> tuple[Decimal | None, Decimal | None]:
    upper = _find_money("缴费基数上限", segment) or _find_money("上限", segment)
    lower = _find_money("缴费基数下限", segment) or _find_money("下限", segment)
    return upper, lower


def _extract_average_salary(text: str) -> Decimal | None:
    match = re.search(r"(?:平均工资|全口径城镇单位就业人员平均工资)[^。；;]{0,24}?为\s*(\d{3,6}(?:\.\d{1,2})?)\s*元", text)
    return _money(match.group(1)) if match else None


def _date(year: str, month: str, day: str = "1") -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_dates(segment: str) -> tuple[str | None, str | None]:
    range_match = re.search(
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日\s*至\s*(20\d{2})年(\d{1,2})月(\d{1,2})日",
        segment,
    )
    if range_match:
        return (
            _date(range_match.group(1), range_match.group(2), range_match.group(3)),
            _date(range_match.group(4), range_match.group(5), range_match.group(6)),
        )
    date_match = DATE_RE.search(segment)
    if date_match:
        return _date(date_match.group(1), date_match.group(2), date_match.group(3)), None
    month_match = MONTH_RE.search(segment)
    if month_match:
        return _date(month_match.group(1), month_match.group(2)), None
    return None, None


def _extract_year(title: str, text: str, publish_date: str | None) -> int | None:
    for source in (title, text, publish_date or ""):
        match = YEAR_RE.search(source or "")
        if match:
            return int(match.group(1))
    return None


def _infer_region_from_url(url: str) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    from urllib.parse import urlparse

    hostname = (urlparse(url).hostname or "").lower()
    for suffix, values in REGION_HINTS.items():
        if hostname == suffix or hostname.endswith("." + suffix):
            return values
    return None, None, None, None, None


def _extract_insurance_types(segment: str, whole_text: str) -> list[str]:
    found: list[str] = []
    for keyword, insurance_type in INSURANCE_TYPE_MAP.items():
        if keyword in segment and insurance_type not in found:
            found.append(insurance_type)
    if found:
        return found
    if any(term in segment for term in ("各项社会保险", "社会保险有关险种", "社保缴费基数", "社会保险费")):
        return ["all"]
    if any(keyword in whole_text for keyword in INSURANCE_TYPE_MAP):
        return ["unknown"]
    return ["all"]


def _extract_issuing_agency(article: dict[str, Any], text: str) -> str | None:
    if article.get("issuing_agency"):
        return article.get("issuing_agency")
    match = re.search(r"发布机构[:：]\s*([^\s。；;]{3,40})", text)
    if match:
        return match.group(1)
    tail = text[-260:]
    agencies = re.findall(r"([\u4e00-\u9fa5]{2,40}(?:人力资源和社会保障局|税务局|医疗保障局|社会保险基金管理局))", tail)
    return "、".join(dict.fromkeys(agencies)) if agencies else None


def _candidate_segments(text: str) -> list[str]:
    pieces = [item.strip() for item in SENTENCE_SPLIT_RE.split(text or "") if item.strip()]
    segments: list[str] = []
    for index, piece in enumerate(pieces):
        if "上限" in piece and "下限" in piece and MONEY_RE.search(piece):
            prefix = pieces[index - 1] if index > 0 and len(pieces[index - 1]) < 80 else ""
            segments.append((prefix + piece).strip())
    if not segments and "上限" in text and "下限" in text:
        segments.append(text[:1200])
    return segments


def calculate_confidence(article: dict[str, Any], record: dict[str, Any]) -> Decimal:
    text = article.get("clean_text") or article.get("text") or ""
    title = article.get("title") or ""
    score = Decimal("0.00")
    if is_gov_cn_url(article.get("source_url") or article.get("url") or ""):
        score += Decimal("0.20")
    if is_candidate_title(title):
        score += Decimal("0.25")
    if "上限" in text and "下限" in text:
        score += Decimal("0.20")
    if record.get("upper_limit") is not None or record.get("lower_limit") is not None:
        score += Decimal("0.20")
    if record.get("effective_start_date") or record.get("year"):
        score += Decimal("0.10")
    if record.get("issuing_agency"):
        score += Decimal("0.05")
    return min(score, Decimal("1.00")).quantize(Decimal("0.01"))


def extract_social_security_limit_info(article: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract one or more social-security base-limit records from an article."""

    title = article.get("title") or article.get("source_title") or ""
    text = article.get("clean_text") or article.get("text") or article.get("raw_text") or ""
    source_url = article.get("source_url") or article.get("url") or ""
    region_code, region_name, province_name, city_name, county_name = _infer_region_from_url(source_url)
    region_code = article.get("region_code") or region_code
    region_name = article.get("region_name") or region_name
    province_name = article.get("province_name") or province_name
    city_name = article.get("city_name") or city_name
    county_name = article.get("county_name") or county_name

    year = article.get("year") or _extract_year(title, text, article.get("publish_date"))
    agency = _extract_issuing_agency(article, text)
    average_salary = _extract_average_salary(text)

    records: list[dict[str, Any]] = []
    for segment in _candidate_segments(text):
        upper, lower = _extract_upper_lower(segment)
        if upper is None and lower is None:
            continue
        start_date, end_date = _extract_dates(segment)
        for insurance_type in _extract_insurance_types(segment, text):
            record = {
                "region_code": region_code,
                "region_name": region_name,
                "province_name": province_name,
                "city_name": city_name,
                "county_name": county_name,
                "year": int(year) if year else None,
                "insurance_type": insurance_type,
                "upper_limit": upper,
                "lower_limit": lower,
                "average_salary": average_salary,
                "effective_start_date": start_date,
                "effective_end_date": end_date,
                "publish_date": article.get("publish_date"),
                "issuing_agency": agency,
                "source_url": source_url,
                "source_title": title,
                "source_article_id": article.get("source_article_id") or article.get("id"),
                "raw_text": text,
            }
            record["confidence"] = calculate_confidence(article, record)
            records.append(record)
    unique: list[dict[str, Any]] = []
    seen = set()
    for record in records:
        key = (
            record.get("insurance_type"),
            record.get("upper_limit"),
            record.get("lower_limit"),
            record.get("effective_start_date"),
            record.get("effective_end_date"),
            record.get("source_url"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique
