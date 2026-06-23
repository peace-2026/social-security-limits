---
name: monitor-social-security-limits
description: Monitor and parse China gov.cn notices about social security contribution base upper/lower limits. Use when the user asks to crawl, monitor, test-parse, extract, compare, or package workflows for 社保缴费基数上下限, 社会保险缴费基数上下限, 社保缴费工资基数, or related official gov.cn update notices.
---

# Monitor Social Security Limits

Use this skill to identify official `gov.cn` social-security contribution base-limit notices, extract upper/lower amounts, and record updates.

## Core Rules

- Trust only URLs whose hostname is `gov.cn` or ends with `.gov.cn`.
- Do not infer article validity from URL patterns.
- Screen by title keywords, then confirm with body text containing `上限`, `下限`, and amounts such as `37302元/月`.
- During first fetch, keep only the requested target year unless the body explicitly says the data applies to that year.
- Exclude non-social-security topics such as `住房公积金`, `社保卡`, `职业培训`, `招聘公告`, and `财政预算`.

## Bundled Code

The reusable crawler package is in `scripts/social_security_crawler/`.

Use the CLI wrapper:

```bash
python3 scripts/run_social_security_crawler.py parse-url <url> --year 2025
python3 scripts/run_social_security_crawler.py init-db --db ./social_security_crawler.sqlite3
python3 scripts/run_social_security_crawler.py discover --year 2026 --db ./social_security_crawler.sqlite3
python3 scripts/run_social_security_crawler.py crawl --scope-type region --scope-id 310000 --year 2026 --db ./social_security_crawler.sqlite3
```

Set `SOCIAL_SECURITY_CRAWLER_DB` or pass `--db` to choose the SQLite database path.

## Workflow

1. For nationwide discovery without known URLs, run `discover --year <year>`. It searches `site:gov.cn` with each region name and only persists confirmed gov.cn notices.
2. If the `region` table is empty, `discover` seeds province-level regions automatically. For city/county coverage, import rows into `region` first, then run `discover --levels province,city,county`.
3. For a single article, run `parse-url` and inspect `is_gov_cn`, `is_candidate`, `is_confirmed`, `confidence`, and `extracted_records`.
4. For known monitoring sources, initialize the database, insert rows into `region_watch_source`, then run `crawl`.
5. For first-time scope runs, expect `initial_fetch`; after a successful init state, later runs use `daily_monitor`.
6. Check extracted records in `social_security_base_limit` and update events in `update_event`.
7. If schema details are needed, read `references/schema.sql`.

## Validation

When modifying bundled crawler code, run from this skill directory:

```bash
PYTHONPATH=scripts python3 -m compileall scripts/social_security_crawler
```
