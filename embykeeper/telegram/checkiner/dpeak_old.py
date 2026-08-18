from json import JSONDecodeError
from datetime import datetime

from curl_cffi.requests import AsyncSession, RequestsError, Response

from embykeeper.runinfo import RunStatus
from embykeeper.utils import show_exception

from .. import get_telegram_proxy_str

from . import BotCheckin

__ignore__ = True


class DPeakCheckin(BotCheckin):
    name = "DPeak"
    bot_username = "emby_dpeak_bot"
    additional_auth = ["prime"]

    async def send_checkin(self, **kw):
        try:
            async with AsyncSession(
                proxy=get_telegram_proxy_str(curl=True), impersonate="edge", allow_redirects=True
            ) as session:
                tgid = self.client.me.id
                current_time = datetime.now()
                date_str = current_time.strftime("%Y-%m-%d")

                # Get info
                resp: Response = await session.get(f"https://miniapp.bwihz.cn/records/checkins/{tgid}.json")
                if resp.ok:
                    result = resp.json()
                    last_checkin = result["lastCheckIn"]
                    streak = result["streak"]
                    checkin_history = result.get("checkInHistory", {})
                else:
                    last_checkin = date_str
                    streak = 0
                    checkin_history = {}

                # First request to get token
                resp: Response = await session.post(
                    "https://miniapp.bwihz.cn/api/token.php", json={"tgid": tgid, "action": "checkin"}
                )
                token_data = resp.json()
                token = token_data["token"]

                # Second request to perform check-in
                timestamp = int(current_time.timestamp())
                iso_time = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+08:00"

                checkin_data = {
                    "tgid": tgid,
                    "checkInData": {
                        "lastCheckIn": last_checkin,
                        "streak": streak + 1,
                        "checkInHistory": checkin_history,
                    },
                    "clientTime": iso_time,
                    "clientTimestamp": timestamp,
                    "token": token,
                }
                resp = await session.post(
                    "https://miniapp.bwihz.cn/api/checkin_record.php", json=checkin_data
                )
                result = resp.json()

                if result.get("success"):
                    details = result["checkInDetails"]
                    add_points = details["totalReward"]
                    self.log.info(f"[yellow]签到成功[/]: + {add_points} 分.")
                    return await self.finish(RunStatus.SUCCESS, "签到成功")
                else:
                    error = result.get("error", None)
                    if error:
                        if "签到过了" in error:
                            self.log.info(f"今日已经签到过了.")
                            return await self.finish(RunStatus.NONEED, "今日已签到")
                        self.log.info(f"签到失败: {error}.")
                    else:
                        self.log.info(f"签到失败, 请求状态为 {resp.status_code}:\n{result}.")
                    return await self.retry()

        except (RequestsError, OSError, JSONDecodeError) as e:
            self.log.info(f"签到失败: 无法连接签到页面 ({e.__class__.__name__}: {e}).")
            return await self.retry()
