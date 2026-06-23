"""Nationwide social-security contribution base limit crawler."""

from .crawler import (
    run_auto_discovery,
    run_daily_monitor,
    run_initial_fetch,
    run_search_fallback,
    run_social_security_limit_crawler,
    test_parse_single_url,
)
from .extractor import extract_social_security_limit_info
from .rules import (
    detect_update,
    get_crawler_run_mode,
    is_candidate_title,
    is_confirmed_social_security_limit_article,
    is_gov_cn_url,
    is_target_year_article,
    should_initial_fetch,
)

__all__ = [
    "detect_update",
    "extract_social_security_limit_info",
    "get_crawler_run_mode",
    "is_candidate_title",
    "is_confirmed_social_security_limit_article",
    "is_gov_cn_url",
    "is_target_year_article",
    "run_daily_monitor",
    "run_auto_discovery",
    "run_initial_fetch",
    "run_search_fallback",
    "run_social_security_limit_crawler",
    "should_initial_fetch",
    "test_parse_single_url",
]
