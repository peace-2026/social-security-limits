from __future__ import annotations

from typing import Any, Protocol


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        ...


DEFAULT_REGION_SEEDS: tuple[dict[str, str], ...] = (
    {"region_code": "110000", "region_name": "北京市", "region_level": "province"},
    {"region_code": "120000", "region_name": "天津市", "region_level": "province"},
    {"region_code": "130000", "region_name": "河北省", "region_level": "province"},
    {"region_code": "140000", "region_name": "山西省", "region_level": "province"},
    {"region_code": "150000", "region_name": "内蒙古自治区", "region_level": "province"},
    {"region_code": "210000", "region_name": "辽宁省", "region_level": "province"},
    {"region_code": "220000", "region_name": "吉林省", "region_level": "province"},
    {"region_code": "230000", "region_name": "黑龙江省", "region_level": "province"},
    {"region_code": "310000", "region_name": "上海市", "region_level": "province"},
    {"region_code": "320000", "region_name": "江苏省", "region_level": "province"},
    {"region_code": "330000", "region_name": "浙江省", "region_level": "province"},
    {"region_code": "340000", "region_name": "安徽省", "region_level": "province"},
    {"region_code": "350000", "region_name": "福建省", "region_level": "province"},
    {"region_code": "360000", "region_name": "江西省", "region_level": "province"},
    {"region_code": "370000", "region_name": "山东省", "region_level": "province"},
    {"region_code": "410000", "region_name": "河南省", "region_level": "province"},
    {"region_code": "420000", "region_name": "湖北省", "region_level": "province"},
    {"region_code": "430000", "region_name": "湖南省", "region_level": "province"},
    {"region_code": "440000", "region_name": "广东省", "region_level": "province"},
    {"region_code": "450000", "region_name": "广西壮族自治区", "region_level": "province"},
    {"region_code": "460000", "region_name": "海南省", "region_level": "province"},
    {"region_code": "500000", "region_name": "重庆市", "region_level": "province"},
    {"region_code": "510000", "region_name": "四川省", "region_level": "province"},
    {"region_code": "520000", "region_name": "贵州省", "region_level": "province"},
    {"region_code": "530000", "region_name": "云南省", "region_level": "province"},
    {"region_code": "540000", "region_name": "西藏自治区", "region_level": "province"},
    {"region_code": "610000", "region_name": "陕西省", "region_level": "province"},
    {"region_code": "620000", "region_name": "甘肃省", "region_level": "province"},
    {"region_code": "630000", "region_name": "青海省", "region_level": "province"},
    {"region_code": "640000", "region_name": "宁夏回族自治区", "region_level": "province"},
    {"region_code": "650000", "region_name": "新疆维吾尔自治区", "region_level": "province"},
)


REGION_SEARCH_TEMPLATES: tuple[str, ...] = (
    'site:gov.cn "{region_name}" "{year}" "社保缴费基数上下限"',
    'site:gov.cn "{region_name}" "{year}" "社会保险缴费基数上下限"',
    'site:gov.cn "{region_name}" "{year}" "缴纳社会保险费基数"',
    'site:gov.cn "{region_name}" "{year}" "缴费基数" "上限" "下限"',
)


def build_region_queries(region_name: str, year: int) -> list[str]:
    return [template.format(region_name=region_name, year=year) for template in REGION_SEARCH_TEMPLATES]


def load_regions_from_db(db: Any, levels: set[str] | None = None) -> list[dict[str, Any]]:
    clauses = ["enabled = 1"]
    params: list[Any] = []
    if levels:
        placeholders = ",".join("?" for _ in levels)
        clauses.append(f"region_level IN ({placeholders})")
        params.extend(sorted(levels))
    rows = db.fetchall(
        f"""
        SELECT region_code, region_name, region_level, province_name, city_name, county_name
        FROM region
        WHERE {' AND '.join(clauses)}
        ORDER BY region_code
        """,
        params,
    )
    return [dict(row) for row in rows]


def seed_default_regions(db: Any) -> int:
    now = __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    inserted = 0
    for region in DEFAULT_REGION_SEEDS:
        existing = db.fetchone("SELECT id FROM region WHERE region_code = ?", (region["region_code"],))
        if existing:
            continue
        db.execute(
            """
            INSERT INTO region (
                region_code, region_name, region_level, province_name, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                region["region_code"],
                region["region_name"],
                region["region_level"],
                region["region_name"],
                now,
                now,
            ),
        )
        inserted += 1
    return inserted


def discover_region_candidates(
    search_provider: SearchProvider,
    region: dict[str, Any],
    year: int,
    limit_per_query: int = 10,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for query in build_region_queries(str(region["region_name"]), year):
        for item in search_provider.search(query, limit=limit_per_query):
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "url": url,
                    "title": item.get("title") or "",
                    "query": query,
                    "region_code": str(region.get("region_code") or ""),
                    "region_name": str(region.get("region_name") or ""),
                }
            )
    return results
