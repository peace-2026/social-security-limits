from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


BLOCK_TAGS = {
    "article",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "li",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}


class GovHTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.in_style = False
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "script":
            self.in_script = True
        elif tag == "style":
            self.in_style = True
        elif tag == "title":
            self.in_title = True
        elif tag == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._current_link_text = []
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False
        elif tag == "title":
            self.in_title = False
        elif tag == "a":
            if self._current_href:
                self.links.append(
                    {
                        "url": self._current_href,
                        "title": normalize_space("".join(self._current_link_text)),
                    }
                )
            self._current_href = None
            self._current_link_text = []
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_script or self.in_style:
            return
        if self.in_title:
            self.title_parts.append(data)
        if self._current_href:
            self._current_link_text.append(data)
        self.text_parts.append(data)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _extract_h1(html_text: str) -> str | None:
    match = re.search(r"<h1[^>]*>([\s\S]{1,300}?)</h1>", html_text, flags=re.I)
    if not match:
        return None
    return normalize_space(re.sub(r"<[^>]+>", " ", match.group(1)))


def _clean_title(title: str) -> str:
    title = normalize_space(title)
    if not title:
        return ""
    title = re.split(r"\s*(?:发布时间|发布日期|成文日期|发布机构|索引号)\s*[:：]", title)[0].strip()
    for sep in ("_", "-", "—", "|"):
        if sep in title:
            head = title.split(sep)[0].strip()
            if 6 <= len(head) <= 80:
                return head
    return title


def _title_score(title: str) -> int:
    title = title or ""
    score = 0
    if any(term in title for term in ("社保", "社会保险", "养老保险", "缴纳社会保险费")):
        score += 3
    if any(term in title for term in ("缴费基数", "上下限", "缴费工资基数", "计发基数")):
        score += 3
    if any(term in title for term in ("调整", "公布", "通告", "通知", "公告")):
        score += 1
    if 8 <= len(title) <= 80:
        score += 1
    return score


def _extract_title(html_text: str, parsed_title: str, clean_text: str) -> str:
    candidates: list[str] = []
    name_match = re.search(r"(?:名称|标题)\s*[:：]\s*([^\n。]{6,90})", clean_text)
    if name_match:
        candidates.append(name_match.group(1))
    article_title_match = re.search(
        r"(关于[^\n。]{0,70}(?:社保|社会保险|养老保险|缴纳社会保险费)[^\n。]{0,70}(?:通告|通知|公告))",
        clean_text,
    )
    if article_title_match:
        candidates.append(article_title_match.group(1))
    candidates.extend([_extract_h1(html_text) or "", parsed_title or "", clean_text[:80]])
    cleaned = [_clean_title(candidate) for candidate in candidates if _clean_title(candidate)]
    if not cleaned:
        return ""
    return max(cleaned, key=_title_score)


def _extract_publish_date(clean_text: str) -> str | None:
    patterns = (
        r"(?:发布时间|发布日期|成文日期|发布日期：|发布时间：)\s*[:：]?\s*(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})",
        r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})\s*(?:发布|印发)?",
    )
    for pattern in patterns:
        match = re.search(pattern, clean_text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


def _extract_issuing_agency(clean_text: str) -> str | None:
    match = re.search(r"(?:发布机构|信息来源|来源)\s*[:：]\s*([^\n。；;]{3,80})", clean_text)
    if match:
        agency = normalize_space(match.group(1))
        agency = re.split(r"\s+(?:成文日期|名称|文号|发布日期|主题词)", agency)[0].strip()
        return agency
    agencies = re.findall(r"([\u4e00-\u9fa5]{2,40}(?:人力资源和社会保障局|税务局|医疗保障局|人民政府))", clean_text[-320:])
    return "、".join(dict.fromkeys(agencies)) if agencies else None


def _extract_body_by_density(html_text: str) -> str:
    parser = GovHTMLTextParser()
    parser.feed(html_text)
    lines = [normalize_space(line) for line in "".join(parser.text_parts).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    best_start = 0
    best_score = -1
    for start in range(len(lines)):
        window = lines[start : start + 8]
        score = sum(len(line) for line in window) - sum(line.count("首页") + line.count("导航") for line in window) * 20
        if score > best_score:
            best_score = score
            best_start = start
    return normalize_space("\n".join(lines[best_start : best_start + 24]))


def common_gov_parser(html_text: str, url: str) -> dict[str, Any]:
    """Parse common government article/list pages."""

    parser = GovHTMLTextParser()
    parser.feed(html_text or "")
    clean_text = _extract_body_by_density(html_text or "")
    title = _extract_title(html_text or "", "".join(parser.title_parts), clean_text)
    links = []
    for link in parser.links:
        href = link.get("url") or ""
        if href.startswith("javascript:") or href.startswith("#"):
            continue
        links.append({"url": urljoin(url, href), "title": link.get("title") or ""})

    return {
        "title": title,
        "publish_date": _extract_publish_date(clean_text),
        "issuing_agency": _extract_issuing_agency(clean_text),
        "clean_text": clean_text,
        "links": links,
    }
