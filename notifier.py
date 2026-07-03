import logging
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

EMOJI_OVERDUE = "🔴"
EMOJI_URGENT = "🟡"
EMOJI_UPCOMING = "🟢"
EMOJI_ERROR = "⚠️"
EMOJI_CHANGED = "📅"


def _days_label(days: int) -> str:
    if days < 0:
        return f"overdue by {abs(days)} day{'s' if abs(days) != 1 else ''}"
    if days == 0:
        return "due TODAY"
    return f"{days} day{'s' if days != 1 else ''} left"


def _status_emoji(days: int) -> str:
    if days < 0:
        return EMOJI_OVERDUE
    if days <= 7:
        return EMOJI_URGENT
    return EMOJI_UPCOMING


def _escape(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a plain-text message via Telegram. Returns True on success."""
    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def notify_deadline_alert(
    bot_token: str,
    chat_id: str,
    name: str,
    url: str,
    deadline: date,
    days_left: int,
) -> bool:
    emoji = _status_emoji(days_left)
    label = _days_label(days_left)
    text = (
        f"{emoji} <b>Deadline alert</b>\n\n"
        f"<b>{name}</b>\n"
        f"🔗 <a href=\"{url}\">{url}</a>\n"
        f"📆 Deadline: <b>{deadline.strftime('%d %B %Y')}</b>\n"
        f"⏱ {label.capitalize()}"
    )
    return send_message(bot_token, chat_id, text)


def notify_deadline_changed(
    bot_token: str,
    chat_id: str,
    name: str,
    url: str,
    old_deadline: date,
    new_deadline: date,
) -> bool:
    direction = "moved earlier" if new_deadline < old_deadline else "extended"
    text = (
        f"{EMOJI_CHANGED} <b>Deadline changed</b>\n\n"
        f"<b>{name}</b>\n"
        f"🔗 <a href=\"{url}\">{url}</a>\n"
        f"Was: {old_deadline.strftime('%d %B %Y')}\n"
        f"Now: <b>{new_deadline.strftime('%d %B %Y')}</b>\n"
        f"({direction})"
    )
    return send_message(bot_token, chat_id, text)


def notify_fetch_error(
    bot_token: str,
    chat_id: str,
    name: str,
    url: str,
    error: str,
) -> bool:
    text = (
        f"{EMOJI_ERROR} <b>Fetch error</b>\n\n"
        f"<b>{name}</b>\n"
        f"🔗 <a href=\"{url}\">{url}</a>\n"
        f"Error: {error}"
    )
    return send_message(bot_token, chat_id, text)


def notify_summary(
    bot_token: str,
    chat_id: str,
    results: list[dict],
) -> bool:
    """Send a daily digest of all tracked deadlines."""
    if not results:
        return True

    lines = ["📋 <b>Daily deadline summary</b>\n"]
    for r in sorted(results, key=lambda x: x.get("days_left", 9999)):
        name = r["name"]
        days = r.get("days_left")
        deadline = r.get("deadline")
        if deadline is None:
            lines.append(f"  {EMOJI_ERROR} {name} — no deadline found")
            continue
        emoji = _status_emoji(days)
        label = _days_label(days)
        lines.append(f"  {emoji} <b>{name}</b> — {label} ({deadline.strftime('%d %b')})")

    return send_message(bot_token, chat_id, "\n".join(lines))
