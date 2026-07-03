import os
from dataclasses import dataclass


@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    check_interval_hours: int
    days_warning_threshold: int
    websites_file: str
    state_file: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID environment variable is not set")

        return cls(
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            check_interval_hours=int(os.environ.get("CHECK_INTERVAL_HOURS", "24")),
            days_warning_threshold=int(os.environ.get("DAYS_WARNING_THRESHOLD", "7")),
            websites_file=os.environ.get("WEBSITES_FILE", "websites.json"),
            state_file=os.environ.get("STATE_FILE", "state.json"),
        )
