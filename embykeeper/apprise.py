import apprise
from loguru import logger
from rich.text import Text

from embykeeper.config import config

logger = logger.bind(scheme="notifier", nonotify=True)

OFFICIAL_TELEGRAM_API_URL = "https://api.telegram.org"


def _get_telegram_notify_url(uri: str):
    base_url = OFFICIAL_TELEGRAM_API_URL
    if uri.startswith("tgram://"):
        notifier = getattr(config, "notifier", None)
        telegram_api_url = getattr(notifier, "telegram_api_url", None) if notifier else None
        if telegram_api_url:
            base_url = str(telegram_api_url)
    return base_url.rstrip("/") + "/bot"


def _apply_telegram_api_url(uri: str):
    import apprise.plugins.telegram as telegram_plugin

    telegram_plugin.NotifyTelegram.notify_url = _get_telegram_notify_url(uri)


class AppriseStream:
    def __init__(self, uri: str):
        _apply_telegram_api_url(uri)
        self.apobj = apprise.Apprise()
        self.apobj.add(uri)

    def write(self, message):
        message = message.strip()
        level, _, body = message.partition("#")
        level = level.lower()
        body = Text.from_markup(body).plain

        notify_type = apprise.NotifyType.INFO
        if level == "warning":
            notify_type = apprise.NotifyType.WARNING
        elif level in ("error", "critical"):
            notify_type = apprise.NotifyType.FAILURE
        elif level == "success":
            notify_type = apprise.NotifyType.SUCCESS

        if not self.apobj.notify(body=body, title="Embykeeper", notify_type=notify_type):
            logger.warning("Failed to send notification via Apprise.")

    def close(self):
        pass

    async def join(self):
        pass
