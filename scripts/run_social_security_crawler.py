#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from social_security_crawler import run_auto_discovery, run_social_security_limit_crawler, test_parse_single_url
from social_security_crawler.discovery import seed_default_regions
from social_security_crawler.storage import SQLiteStore


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _db(path: str | None) -> SQLiteStore:
    if path:
        os.environ["SOCIAL_SECURITY_CRAWLER_DB"] = path
        return SQLiteStore(path)
    return SQLiteStore(os.environ.get("SOCIAL_SECURITY_CRAWLER_DB", "social_security_crawler.sqlite3"))


def init_db(args: argparse.Namespace) -> int:
    db = _db(args.db)
    db.init_schema()
    print(f"initialized: {db.path}")
    return 0


def parse_url(args: argparse.Namespace) -> int:
    result = test_parse_single_url(args.url, args.year)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def crawl(args: argparse.Namespace) -> int:
    db = _db(args.db)
    db.init_schema()
    records = run_social_security_limit_crawler(
        args.scope_type,
        args.scope_id,
        args.year,
        db=db,
    )
    print(json.dumps(records, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def seed_regions(args: argparse.Namespace) -> int:
    db = _db(args.db)
    db.init_schema()
    inserted = seed_default_regions(db)
    print(f"seeded default province-level regions: {inserted}")
    return 0


def discover(args: argparse.Namespace) -> int:
    db = _db(args.db)
    db.init_schema()
    levels = set(args.levels.split(",")) if args.levels else None
    records = run_auto_discovery(
        args.year,
        db=db,
        region_levels=levels,
        limit_regions=args.limit_regions,
        limit_per_query=args.limit_per_query,
    )
    print(json.dumps(records, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor gov.cn social security base limit notices.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-db", help="Initialize the SQLite schema.")
    init.add_argument("--db", default=None, help="SQLite database path.")
    init.set_defaults(func=init_db)

    parse = subparsers.add_parser("parse-url", help="Parse and extract a single gov.cn URL.")
    parse.add_argument("url")
    parse.add_argument("--year", type=int, required=True)
    parse.set_defaults(func=parse_url)

    crawl_cmd = subparsers.add_parser("crawl", help="Run initial_fetch or daily_monitor.")
    crawl_cmd.add_argument("--scope-type", required=True, choices=("region", "source", "user", "account"))
    crawl_cmd.add_argument("--scope-id", required=True)
    crawl_cmd.add_argument("--year", type=int, required=True)
    crawl_cmd.add_argument("--db", default=None, help="SQLite database path.")
    crawl_cmd.set_defaults(func=crawl)

    seed = subparsers.add_parser("seed-regions", help="Insert built-in province-level region seeds.")
    seed.add_argument("--db", default=None, help="SQLite database path.")
    seed.set_defaults(func=seed_regions)

    discover_cmd = subparsers.add_parser("discover", help="Search gov.cn by region names, then parse confirmed notices.")
    discover_cmd.add_argument("--year", type=int, required=True)
    discover_cmd.add_argument("--db", default=None, help="SQLite database path.")
    discover_cmd.add_argument("--levels", default=None, help="Comma-separated region levels, e.g. province,city,county.")
    discover_cmd.add_argument("--limit-regions", type=int, default=None, help="Limit number of regions for smoke tests.")
    discover_cmd.add_argument("--limit-per-query", type=int, default=10)
    discover_cmd.set_defaults(func=discover)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
