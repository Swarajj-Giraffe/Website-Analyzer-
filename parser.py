import re
import logging
from datetime import date, datetime
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Patterns tried in order; first match wins.
# Each pattern must yield at least one named group: day, month, year.
DATE_PATTERNS = [
    # ISO: 2025-03-15
    (r"\b(?P<year>20\d{2})[.\-/](?P<month>\d{1,2})[.\-/](?P<day>\d{1,2})\b", "%Y-%m-%d"),
    # Long: March 15, 2025 / 15 March 2025
    (r"\b(?P<day>\d{1,2})\s+(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,\s]+(?P<year>20\d{2})\b", None),
    (r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?P<day>\d{1,2})[,\s]+(?P<year>20\d{2})\b", None),
    # Short: 15/03/2025 or 03/15/2025 (tries both interpretations)
    (r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>20\d{2})\b", "%d/%m/%Y"),
]

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Keywords that indicate a date is a deadline, not just any date on the page
DEADLINE_KEYWORDS = [
    "deadline", "submission", "submit", "due date", "due by", "closes",
    "closing date", "last date", "final date", "applications close",
    "entries close", "apply by", "register by", "entry deadline",
]

DEADLINE_CONTEXT_WINDOW = 200  # characters around a keyword to search for a date


@dataclass
class ParseResult:
    url: str
    deadline: Optional[date]
    raw_text: Optional[str]  # the snippet that contained the date
    error: Optional[str]


def _parse_month(raw: str) -> int:
    return MONTH_MAP[raw.strip().lower()]


def _try_parse_date(day: str, month: str, year: str) -> Optional[date]:
    try:
        m = int(month) if month.isdigit() else _parse_month(month)
        return date(int(year), m, int(day))
    except (ValueError, KeyError):
        return None


def _extract_dates_from_text(text: str) -> list[tuple[date, str]]:
    """Return all (date, snippet) pairs found in text."""
    results = []
    for pattern, _ in DATE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            g = m.groupdict()
            d = _try_parse_date(g.get("day", "1"), g["month"], g["year"])
            if d and d >= date.today():
                snippet = text[max(0, m.start() - 40): m.end() + 40].strip()
                results.append((d, snippet))
    return results


def _score_candidate(snippet: str, context: str) -> int:
    """Higher score = more likely to be the submission deadline."""
    score = 0
    combined = (snippet + " " + context).lower()
    for kw in DEADLINE_KEYWORDS:
        if kw in combined:
            score += 10
    return score


def fetch_deadline(url: str, css_selector: Optional[str] = None, timeout: int = 15) -> ParseResult:
    """
    Fetch a page and extract the most likely submission deadline.

    Args:
        url: The page to fetch.
        css_selector: Optional CSS selector to narrow the search area.
        timeout: HTTP request timeout in seconds.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; DeadlineMonitorBot/1.0; "
                "+https://github.com/your-org/ward-deadline-monitor)"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ParseResult(url=url, deadline=None, raw_text=None, error=str(exc))

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script / style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    if css_selector:
        node = soup.select_one(css_selector)
        search_text = node.get_text(" ", strip=True) if node else soup.get_text(" ", strip=True)
    else:
        search_text = soup.get_text(" ", strip=True)

    # Strategy 1: find a deadline keyword, then look for a date nearby
    best: Optional[tuple[date, str]] = None
    best_score = -1

    for kw in DEADLINE_KEYWORDS:
        for m in re.finditer(re.escape(kw), search_text, re.IGNORECASE):
            context_start = max(0, m.start() - DEADLINE_CONTEXT_WINDOW)
            context_end = min(len(search_text), m.end() + DEADLINE_CONTEXT_WINDOW)
            context = search_text[context_start:context_end]
            for d, snippet in _extract_dates_from_text(context):
                score = _score_candidate(snippet, context)
                if score > best_score:
                    best_score = score
                    best = (d, snippet)

    # Strategy 2: fall back to the earliest future date on the page
    if best is None:
        candidates = _extract_dates_from_text(search_text)
        if candidates:
            candidates.sort(key=lambda x: x[0])
            best = candidates[0]
            logger.debug("No keyword context found for %s; using earliest future date", url)

    if best is None:
        return ParseResult(url=url, deadline=None, raw_text=None, error="No future date found on page")

    found_date, snippet = best
    logger.info("Found deadline %s for %s", found_date, url)
    return ParseResult(url=url, deadline=found_date, raw_text=snippet, error=None)
