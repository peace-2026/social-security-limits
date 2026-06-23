CREATE TABLE IF NOT EXISTS region (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code VARCHAR(32) NOT NULL UNIQUE,
    region_name VARCHAR(128) NOT NULL,
    region_level VARCHAR(32) NOT NULL,
    parent_region_code VARCHAR(32),
    province_name VARCHAR(128),
    city_name VARCHAR(128),
    county_name VARCHAR(128),
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS region_watch_source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code VARCHAR(32) NOT NULL,
    region_name VARCHAR(128) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    base_domain VARCHAR(255),
    list_url TEXT,
    search_url TEXT,
    sitemap_url TEXT,
    page_type VARCHAR(64),
    parser_type VARCHAR(64),
    enabled BOOLEAN DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crawler_init_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type VARCHAR(64) NOT NULL,
    scope_id VARCHAR(128) NOT NULL,
    region_code VARCHAR(32),
    source_id INTEGER,
    target_year INT NOT NULL,
    init_status VARCHAR(32) NOT NULL,
    first_fetch_at TIMESTAMP,
    last_checked_at TIMESTAMP,
    last_success_at TIMESTAMP,
    fail_count INT DEFAULT 0,
    fail_reason TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(scope_type, scope_id, target_year)
);

CREATE TABLE IF NOT EXISTS crawled_article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code VARCHAR(32),
    region_name VARCHAR(128),
    source_type VARCHAR(64),
    source_url TEXT NOT NULL,
    canonical_url TEXT,
    domain VARCHAR(255),
    title TEXT,
    publish_date DATE,
    crawl_time TIMESTAMP,
    raw_html TEXT,
    clean_text TEXT,
    content_hash VARCHAR(128),
    title_hash VARCHAR(128),
    is_gov_cn BOOLEAN DEFAULT FALSE,
    is_candidate BOOLEAN DEFAULT FALSE,
    is_confirmed BOOLEAN DEFAULT FALSE,
    matched_keywords TEXT,
    status VARCHAR(32),
    fail_reason TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crawled_article_canonical_url ON crawled_article(canonical_url);
CREATE INDEX IF NOT EXISTS idx_crawled_article_content_hash ON crawled_article(content_hash);
CREATE INDEX IF NOT EXISTS idx_crawled_article_title_hash ON crawled_article(title_hash);

CREATE TABLE IF NOT EXISTS social_security_base_limit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code VARCHAR(32),
    region_name VARCHAR(128),
    province_name VARCHAR(128),
    city_name VARCHAR(128),
    county_name VARCHAR(128),
    year INT,
    insurance_type VARCHAR(64),
    upper_limit DECIMAL(12, 2),
    lower_limit DECIMAL(12, 2),
    average_salary DECIMAL(12, 2),
    effective_start_date DATE,
    effective_end_date DATE,
    publish_date DATE,
    issuing_agency VARCHAR(255),
    source_url TEXT,
    source_title TEXT,
    source_article_id INTEGER,
    raw_text TEXT,
    confidence DECIMAL(5, 2),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_base_limit_identity
ON social_security_base_limit(region_code, year, insurance_type);

CREATE TABLE IF NOT EXISTS update_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code VARCHAR(32),
    region_name VARCHAR(128),
    year INT,
    insurance_type VARCHAR(64),
    old_upper_limit DECIMAL(12, 2),
    new_upper_limit DECIMAL(12, 2),
    old_lower_limit DECIMAL(12, 2),
    new_lower_limit DECIMAL(12, 2),
    old_effective_start_date DATE,
    new_effective_start_date DATE,
    source_url TEXT,
    source_title TEXT,
    event_type VARCHAR(64),
    event_status VARCHAR(64),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
