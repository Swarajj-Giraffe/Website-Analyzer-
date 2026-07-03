#!/usr/bin/env python3
"""
ward-deadline-monitor
~~~~~~~~~~~~~~~~~~~~~
Monitors websites for advertisement submission deadlines and sends
Telegram alerts when deadlines are approaching, overdue, or have changed.

Usage:
    python monitor.py            # run once (default, good for cron / GitHub Actions)
    python monitor.py --loop     # run on a schedule (long-running process)
    python monitor.py --test     # send a test Telegram message and exit
    python monitor.py --summary  # send daily digest and exit
"""
import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config import Config
from notifier import (
    notify_deadline_alert,
    notify_deadline_changed,
    notify_fetch_error,
    notify_summary,
    send_message,
)
from parser import fetch_deadline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            logger.warning("State file is corrupt; starting fresh.")
    return {}


def save_state(path: str, state: dict) -> None:
    Path(path).write_text(json.dumps(state, indent=2, default=str))


def load_websites(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        logger.error("websites.json not found at %s", path)
        sys.exit(1)
    sites = json.loads(p.read_text())
    if not isinstance(sites, list):
        logger.error("websites.json must be a JSON array")
        sys.exit(1)
    return sites


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_site(site: dict, state: dict, cfg: Config) -> Optional[dict]:
    """
    Check a single site and fire notifications as needed.
    Returns a result dict for the summary digest.
    """
    name: str = site["name"]
    url: str = site["url"]
    selector: Optional[str] = site.get("selector")
    notify_days: list[int] = site.get("notify_days", [14, 7, 3, 1, 0])

    logger.info("Checking: %s (%s)", name, url)
    result = fetch_deadline(url, css_selector=selector)

    site_state = state.get(url, {})

    if result.error:
        if site_state.get("last_error") != result.error:
            notify_fetch_error(cfg.telegram_bot_token, cfg.telegram_chat_id, name, url, result.error)
            site_state["last_error"] = result.error
        state[url] = site_state
        return {"name": name, "url": url, "deadline": None, "days_left": None}

    # Clear any previous error
    site_state.pop("last_error", None)

    deadline: date = result.deadline
    days_left = (deadline - date.today()).days

    # Detect change vs previously known deadline
    prev_deadline_str: Optional[str] = site_state.get("deadline")
    if prev_deadline_str:
        prev_deadline = date.fromisoformat(prev_deadline_str)
        if prev_deadline != deadline:
            logger.info("Deadline changed for %s: %s -> %s", name, prev_deadline, deadline)
            notify_deadline_changed(
                cfg.telegram_bot_token, cfg.telegram_chat_id,
                name, url, prev_deadline, deadline,
            )

    # Alert if days_left matches a notify_days threshold and we haven't fired it yet
    notified_days: list[int] = site_state.get("notified_days", [])
    if days_left in notify_days and days_left not in notified_days:
        logger.info("Alerting for %s: %d days left", name, days_left)
        notify_deadline_alert(
            cfg.telegram_bot_token, cfg.telegram_chat_id,
            name, url, deadline, days_left,
        )
        notified_days.append(days_left)

    # Reset notified_days when a new deadline is detected
    if prev_deadline_str and date.fromisoformat(prev_deadline_str) != deadline:
        notified_days = [days_left] if days_left in notify_days else []

    site_state["deadline"] = deadline.isoformat()
    site_state["days_left"] = days_left
    site_state["notified_days"] = notified_days
    site_state["last_checked"] = datetime.utcnow().isoformat()
    state[url] = site_state

    return {"name": name, "url": url, "deadline": deadline, "days_left": days_left}


def run_once(cfg: Config, send_digest: bool = False) -> None:
    websites = load_websites(cfg.websites_file)
    state = load_state(cfg.state_file)

    results = []
    for site in websites:
        try:
            r = check_site(site, state, cfg)
            if r:
                results.append(r)
        except Exception as exc:
            logger.exception("Unexpected error checking %s: %s", site.get("name"), exc)

    save_state(cfg.state_file, state)

    if send_digest:
        notify_summary(cfg.telegram_bot_token, cfg.telegram_chat_id, results)

    logger.info("Done. Checked %d site(s).", len(websites))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ward deadline monitor")
    parser.add_argument("--loop", action="store_true", help="Run on a schedule instead of once")
    parser.add_argument("--test", action="store_true", help="Send a test message and exit")
    parser.add_argument("--summary", action="store_true", help="Send daily digest and exit")
    args = parser.parse_args()

    cfg = Config.from_env()

    if args.test:
        ok = send_message(cfg.telegram_bot_token, cfg.telegram_chat_id, "✅ Ward deadline monitor is connected and working.")
        sys.exit(0 if ok else 1)

    if args.loop:
        logger.info("Running in loop mode (interval: %dh)", cfg.check_interval_hours)
        while True:
            run_once(cfg, send_digest=args.summary)
            time.sleep(cfg.check_interval_hours * 3600)
    else:
        run_once(cfg, send_digest=args.summary)


if __name__ == "__main__":
    main()
