from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

import requests

from .extractor import extract_social_security_limit_info
from .discovery import DEFAULT_REGION_SEEDS, discover_region_candidates, load_regions_from_db, seed_default_regions
from .parser import common_gov_parser
from .rules import (
    content_hash,
    detect_update,
    get_crawler_run_mode,
    is_candidate_title,
    is_confirmed_social_security_limit_article,
    is_gov_cn_url,
    is_target_year_article,
    title_region_date_hash,
)
from .storage import SQLiteStore, default_db, row_to_dict, utcnow


USER_AGENT = (
    "Mozilla/5.0 (compatible; SocialSecurityBaseLimitCrawler/1.0; "
    "+https://gov.cn-source-monitor.local)"
)

DOMAIN_SEARCH_TEMPLATES = (
    "site:{domain} 社保 缴费基数 上下限 {target_year}",
    "site:{domain} 社会保险 缴费基数 上限 下限 {target_year}",
    "site:{domain} {target_year}年度 社保缴费基数上下限",
    "site:{domain} 缴纳社会保险费基数 通知 {target_year}",
)

GOV_CN_SEARCH_TEMPLATES = (
    'site:gov.cn "社保缴费基数上下限" "{target_year}"',
    'site:gov.cn "社会保险缴费基数上下限" "{target_year}"',
    'site:gov.cn "缴纳社会保险费基数" "{target_year}"',
)


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        ...


class DuckDuckGoSearchProvider:
    """Small HTML search adapter used only to discover candidate URLs."""

    endpoint = "https://duckduckgo.com/html/"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        response = self.session.get(
            self.endpoint,
            params={"q": query},
            timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        html = response.text
        results: list[dict[str, str]] = []
        for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', html):
            title = re.sub(r"<[^>]+>", " ", match.group(2))
            results.append({"url": match.group(1), "title": re.sub(r"\s+", " ", title).strip()})
            if len(results) >= limit:
                break
        return results


def _session(session: requests.Session | None = None) -> requests.Session:
    return session or requests.Session()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, "", parsed.query, ""))


def fetch_url(url: str, session: requests.Session | None = None, timeout: int = 20) -> str:
    response = _session(session).get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _decimal_to_db(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _domain(url: str) -> str | None:
    return urlparse(url).hostname


def _get_sources(db: SQLiteStore, scope_type: str, scope_id: str) -> list[dict[str, Any]]:
    if scope_type == "source":
        rows = db.fetchall("SELECT * FROM region_watch_source WHERE id = ? AND enabled = 1", (scope_id,))
    elif scope_type == "region":
        rows = db.fetchall(
            "SELECT * FROM region_watch_source WHERE region_code = ? AND enabled = 1",
            (scope_id,),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM region_watch_source WHERE enabled = 1 AND (region_code = ? OR region_name = ?)",
            (scope_id, scope_id),
        )
    return [dict(row) for row in rows]


def _upsert_init_state(
    db: SQLiteStore,
    scope_type: str,
    scope_id: str,
    target_year: int,
    status: str,
    fail_reason: str | None = None,
    source_id: int | None = None,
    region_code: str | None = None,
) -> None:
    now = utcnow()
    existing = db.fetchone(
        "SELECT * FROM crawler_init_state WHERE scope_type = ? AND scope_id = ? AND target_year = ?",
        (scope_type, scope_id, target_year),
    )
    if existing:
        db.execute(
            """
            UPDATE crawler_init_state
            SET init_status = ?,
                first_fetch_at = COALESCE(first_fetch_at, ?),
                last_checked_at = ?,
                last_success_at = CASE WHEN ? = 'success' THEN ? ELSE last_success_at END,
                fail_count = CASE WHEN ? = 'failed' THEN fail_count + 1 ELSE fail_count END,
                fail_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, now, now, status, now, status, fail_reason, now, existing["id"]),
        )
    else:
        db.execute(
            """
            INSERT INTO crawler_init_state (
                scope_type, scope_id, region_code, source_id, target_year, init_status,
                first_fetch_at, last_checked_at, last_success_at, fail_count, fail_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope_type,
                scope_id,
                region_code,
                source_id,
                target_year,
                status,
                now,
                now,
                now if status == "success" else None,
                1 if status == "failed" else 0,
                fail_reason,
                now,
                now,
            ),
        )


def _is_duplicate_article(
    db: SQLiteStore,
    canonical_url: str,
    region_code: str | None,
    title: str,
    publish_date: str | None,
    clean_text: str,
) -> bool:
    title_hash = title_region_date_hash(region_code or "", title, publish_date)
    body_hash = content_hash(clean_text, limit=1000)
    row = db.fetchone(
        """
        SELECT id FROM crawled_article
        WHERE canonical_url = ? OR title_hash = ? OR content_hash = ?
        LIMIT 1
        """,
        (canonical_url, title_hash, body_hash),
    )
    return row is not None


def _save_article(
    db: SQLiteStore,
    article: dict[str, Any],
    raw_html: str,
    status: str,
    fail_reason: str | None = None,
) -> int:
    now = utcnow()
    title_hash = title_region_date_hash(
        article.get("region_code") or "", article.get("title") or "", article.get("publish_date")
    )
    body_hash = content_hash(article.get("clean_text") or "", limit=1000)
    cursor = db.execute(
        """
        INSERT INTO crawled_article (
            region_code, region_name, source_type, source_url, canonical_url, domain,
            title, publish_date, crawl_time, raw_html, clean_text, content_hash, title_hash,
            is_gov_cn, is_candidate, is_confirmed, matched_keywords, status, fail_reason,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article.get("region_code"),
            article.get("region_name"),
            article.get("source_type"),
            article.get("source_url"),
            article.get("canonical_url"),
            article.get("domain"),
            article.get("title"),
            article.get("publish_date"),
            now,
            raw_html,
            article.get("clean_text"),
            body_hash,
            title_hash,
            bool(article.get("is_gov_cn")),
            bool(article.get("is_candidate")),
            bool(article.get("is_confirmed")),
            article.get("matched_keywords"),
            status,
            fail_reason,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def _existing_records(db: SQLiteStore, record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT * FROM social_security_base_limit
        WHERE region_code = ? AND year = ? AND insurance_type = ?
        ORDER BY updated_at, id
        """,
        (record.get("region_code"), record.get("year"), record.get("insurance_type") or "unknown"),
    )
    return [dict(row) for row in rows]


def _save_update_event(db: SQLiteStore, event: dict[str, Any]) -> None:
    now = utcnow()
    db.execute(
        """
        INSERT INTO update_event (
            region_code, region_name, year, insurance_type, old_upper_limit, new_upper_limit,
            old_lower_limit, new_lower_limit, old_effective_start_date, new_effective_start_date,
            source_url, source_title, event_type, event_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get("region_code"),
            event.get("region_name"),
            event.get("year"),
            event.get("insurance_type"),
            _decimal_to_db(event.get("old_upper_limit")),
            _decimal_to_db(event.get("new_upper_limit")),
            _decimal_to_db(event.get("old_lower_limit")),
            _decimal_to_db(event.get("new_lower_limit")),
            event.get("old_effective_start_date"),
            event.get("new_effective_start_date"),
            event.get("source_url"),
            event.get("source_title"),
            event.get("event_type"),
            event.get("event_status") or "pending",
            now,
            now,
        ),
    )


def _save_limit_record(db: SQLiteStore, record: dict[str, Any]) -> int:
    now = utcnow()
    cursor = db.execute(
        """
        INSERT INTO social_security_base_limit (
            region_code, region_name, province_name, city_name, county_name, year, insurance_type,
            upper_limit, lower_limit, average_salary, effective_start_date, effective_end_date,
            publish_date, issuing_agency, source_url, source_title, source_article_id, raw_text,
            confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get("region_code"),
            record.get("region_name"),
            record.get("province_name"),
            record.get("city_name"),
            record.get("county_name"),
            record.get("year"),
            record.get("insurance_type") or "unknown",
            _decimal_to_db(record.get("upper_limit")),
            _decimal_to_db(record.get("lower_limit")),
            _decimal_to_db(record.get("average_salary")),
            record.get("effective_start_date"),
            record.get("effective_end_date"),
            record.get("publish_date"),
            record.get("issuing_agency"),
            record.get("source_url"),
            record.get("source_title"),
            record.get("source_article_id"),
            record.get("raw_text"),
            _decimal_to_db(record.get("confidence")),
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def _process_article_url(
    url: str,
    db: SQLiteStore,
    target_year: int | None = None,
    source: dict[str, Any] | None = None,
    initial_fetch: bool = False,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    canonical_url = canonicalize_url(url)
    if not is_gov_cn_url(canonical_url):
        return []

    raw_html = fetch_url(url, session=session)
    parsed = common_gov_parser(raw_html, canonical_url)
    article = {
        **parsed,
        "source_url": url,
        "canonical_url": canonical_url,
        "domain": _domain(canonical_url),
        "source_type": (source or {}).get("source_type"),
        "region_code": (source or {}).get("region_code"),
        "region_name": (source or {}).get("region_name"),
        "is_gov_cn": True,
    }
    article["is_candidate"] = is_candidate_title(article["title"])
    if initial_fetch and target_year and not is_target_year_article(
        article["title"], article["clean_text"], article["publish_date"], target_year
    ):
        _save_article(db, article, raw_html, "ignored", "not target year")
        return []
    if _is_duplicate_article(
        db,
        canonical_url,
        article.get("region_code"),
        article.get("title") or "",
        article.get("publish_date"),
        article.get("clean_text") or "",
    ):
        return []

    article["is_confirmed"] = is_confirmed_social_security_limit_article(
        article.get("title") or "", article.get("clean_text") or ""
    )
    if not article["is_candidate"] or not article["is_confirmed"]:
        _save_article(db, article, raw_html, "ignored", "keyword or body screen failed")
        return []

    article_id = _save_article(db, article, raw_html, "parsed")
    article["id"] = article_id
    records = [
        record
        for record in extract_social_security_limit_info(article)
        if record.get("confidence") is not None and Decimal(str(record["confidence"])) >= Decimal("0.75")
    ]
    saved: list[dict[str, Any]] = []
    for record in records:
        record["source_article_id"] = article_id
        event = detect_update(record, _existing_records(db, record))
        record_id = _save_limit_record(db, record)
        record["id"] = record_id
        if event:
            _save_update_event(db, event)
        saved.append(record)
    return saved


def _discover_from_source(
    source: dict[str, Any],
    target_year: int | None = None,
    session: requests.Session | None = None,
    max_pages: int = 3,
) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    for key in ("list_url", "search_url", "sitemap_url"):
        url = source.get(key)
        if not url:
            continue
        if target_year:
            url = str(url).format(target_year=target_year, year=target_year)
        try:
            html = fetch_url(url, session=session)
        except requests.RequestException:
            continue
        if key == "sitemap_url":
            for match in re.finditer(r"https?://[^\s<>\"]+", html):
                candidate = match.group(0)
                if is_gov_cn_url(candidate):
                    urls.append({"url": candidate, "title": ""})
        else:
            parsed = common_gov_parser(html, url)
            urls.extend(parsed["links"])
        if len(urls) >= max_pages * 50:
            break
    seen = set()
    filtered = []
    for item in urls:
        url = canonicalize_url(item["url"])
        if url in seen or not is_gov_cn_url(url):
            continue
        seen.add(url)
        if not item.get("title") or is_candidate_title(item.get("title") or ""):
            filtered.append({"url": item["url"], "title": item.get("title") or ""})
    return filtered


def run_initial_fetch(
    scope_type: str,
    scope_id: str,
    target_year: int,
    db: SQLiteStore | None = None,
    search_provider: SearchProvider | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch only target-year social-security base limit data for an uninitialized scope."""

    db = db or default_db()
    sources = _get_sources(db, scope_type, scope_id)
    records: list[dict[str, Any]] = []
    try:
        for source in sources:
            candidates = _discover_from_source(source, target_year=target_year, session=session)
            if search_provider:
                domain = source.get("base_domain") or _domain(source.get("list_url") or "")
                if domain:
                    for template in DOMAIN_SEARCH_TEMPLATES:
                        candidates.extend(search_provider.search(template.format(domain=domain, target_year=target_year)))
            for item in candidates:
                records.extend(
                    _process_article_url(
                        item["url"],
                        db,
                        target_year=target_year,
                        source=source,
                        initial_fetch=True,
                        session=session,
                    )
                )
        if search_provider:
            for template in GOV_CN_SEARCH_TEMPLATES:
                for item in search_provider.search(template.format(target_year=target_year)):
                    records.extend(
                        _process_article_url(
                            item["url"],
                            db,
                            target_year=target_year,
                            initial_fetch=True,
                            session=session,
                        )
                    )
        if records:
            _upsert_init_state(db, scope_type, scope_id, target_year, "success")
        else:
            _upsert_init_state(db, scope_type, scope_id, target_year, "failed", "no valid target-year records")
        return records
    except Exception as exc:
        _upsert_init_state(db, scope_type, scope_id, target_year, "failed", str(exc))
        raise


def run_daily_monitor(
    scope_type: str,
    scope_id: str,
    db: SQLiteStore | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Monitor initialized sources for new or changed articles."""

    db = db or default_db()
    init_state = db.fetchone(
        """
        SELECT * FROM crawler_init_state
        WHERE scope_type = ? AND scope_id = ? AND init_status = 'success'
        ORDER BY target_year DESC, updated_at DESC
        LIMIT 1
        """,
        (scope_type, scope_id),
    )
    target_year = int(init_state["target_year"]) if init_state else datetime.utcnow().year
    sources = _get_sources(db, scope_type, scope_id)
    records: list[dict[str, Any]] = []
    try:
        for source in sources:
            candidates = _discover_from_source(source, target_year=None, session=session, max_pages=3)
            for item in candidates:
                records.extend(_process_article_url(item["url"], db, source=source, session=session))
            db.execute("UPDATE region_watch_source SET last_checked_at = ?, updated_at = ? WHERE id = ?", (utcnow(), utcnow(), source["id"]))
        _upsert_init_state(db, scope_type, scope_id, target_year, "success")
        return records
    except Exception as exc:
        _upsert_init_state(db, scope_type, scope_id, target_year, "failed", str(exc))
        raise


def run_social_security_limit_crawler(
    scope_type: str,
    scope_id: str,
    target_year: int,
    db: SQLiteStore | None = None,
    search_provider: SearchProvider | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    db = db or default_db()
    mode = get_crawler_run_mode(scope_type, scope_id, target_year, db=db)
    if mode == "initial_fetch":
        return run_initial_fetch(scope_type, scope_id, target_year, db=db, search_provider=search_provider, session=session)
    return run_daily_monitor(scope_type, scope_id, db=db, session=session)


def test_parse_single_url(
    url: str,
    target_year: int,
    db: SQLiteStore | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch and parse one URL without writing final records to the database."""

    is_gov = is_gov_cn_url(url)
    if not is_gov:
        return {
            "is_gov_cn": False,
            "title": "",
            "publish_date": None,
            "is_target_year": False,
            "is_candidate": False,
            "is_confirmed": False,
            "extracted_records": [],
            "confidence": 0.0,
        }
    raw_html = fetch_url(url, session=session)
    parsed = common_gov_parser(raw_html, canonicalize_url(url))
    article = {**parsed, "source_url": url}
    is_target = is_target_year_article(
        parsed["title"], parsed["clean_text"], parsed.get("publish_date"), target_year
    )
    is_candidate = is_candidate_title(parsed["title"])
    is_confirmed = is_confirmed_social_security_limit_article(parsed["title"], parsed["clean_text"])
    records = extract_social_security_limit_info(article) if is_confirmed else []
    confidence = max([float(record.get("confidence") or 0) for record in records], default=0.0)
    return {
        "is_gov_cn": True,
        "title": parsed["title"],
        "publish_date": parsed.get("publish_date"),
        "is_target_year": is_target,
        "is_candidate": is_candidate,
        "is_confirmed": is_confirmed,
        "extracted_records": records,
        "confidence": confidence,
    }


def run_search_fallback(
    year: int,
    db: SQLiteStore | None = None,
    search_provider: SearchProvider | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Discover gov.cn URLs from search and process confirmed articles."""

    db = db or default_db()
    search_provider = search_provider or DuckDuckGoSearchProvider(session=session)
    records: list[dict[str, Any]] = []
    for template in GOV_CN_SEARCH_TEMPLATES:
        for item in search_provider.search(template.format(target_year=year)):
            if is_gov_cn_url(item.get("url") or ""):
                records.extend(
                    _process_article_url(
                        item["url"],
                        db,
                        target_year=year,
                        initial_fetch=True,
                        session=session,
                    )
                )
    return records


def run_auto_discovery(
    year: int,
    db: SQLiteStore | None = None,
    search_provider: SearchProvider | None = None,
    session: requests.Session | None = None,
    region_levels: set[str] | None = None,
    limit_regions: int | None = None,
    limit_per_query: int = 10,
    seed_regions_if_empty: bool = True,
) -> list[dict[str, Any]]:
    """Search gov.cn by region names, then parse confirmed target-year notices."""

    db = db or default_db()
    db.init_schema()
    if seed_regions_if_empty and not db.fetchone("SELECT id FROM region LIMIT 1"):
        seed_default_regions(db)
    regions = load_regions_from_db(db, levels=region_levels)
    if not regions:
        regions = [dict(item) for item in DEFAULT_REGION_SEEDS]
    if limit_regions:
        regions = regions[:limit_regions]

    search_provider = search_provider or DuckDuckGoSearchProvider(session=session)
    saved: list[dict[str, Any]] = []
    for region in regions:
        region_saved: list[dict[str, Any]] = []
        source = {
            "region_code": region.get("region_code"),
            "region_name": region.get("region_name"),
            "source_type": "search",
        }
        for item in discover_region_candidates(search_provider, region, year, limit_per_query=limit_per_query):
            if not is_gov_cn_url(item.get("url") or ""):
                continue
            region_saved.extend(
                _process_article_url(
                    item["url"],
                    db,
                    target_year=year,
                    source=source,
                    initial_fetch=True,
                    session=session,
                )
            )
        saved.extend(region_saved)
        _upsert_init_state(
            db,
            "region",
            str(region.get("region_code") or region.get("region_name")),
            year,
            "success" if region_saved else "failed",
            None if region_saved else "no valid target-year records from search discovery",
            region_code=region.get("region_code"),
        )
    return saved
