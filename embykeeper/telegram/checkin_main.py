from __future__ import annotations

import asyncio
from datetime import datetime
import random
from typing import List, Dict, Tuple, Type

from loguru import logger

from embykeeper.schedule import Scheduler
from embykeeper.schema import TelegramAccount
from embykeeper.config import config
from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.utils import AsyncTaskPool, show_exception

from .checkiner import BaseBotCheckin
from .dynamic import extract, get_cls, get_names
from .session import ClientsSession
from .pyrogram import Client

logger = logger.bind(scheme="telechecker")


class CheckinerManager:
    """签到管理器"""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}  # phone -> task
        self._site_tasks: Dict[str, Dict[str, asyncio.Task]] = {}  # phone -> site -> task
        self._schedulers: Dict[str, Scheduler] = {}  # phone -> scheduler
        self._pool = AsyncTaskPool()

        config.on_list_change("telegram.account", self._handle_account_change)
        config.on_change("checkiner", self._handle_config_change)
        config.on_change("site.checkiner", self._handle_config_change)

    def _handle_config_change(self, *args):
        """Handle changes to the checkiner configuration"""
        # Stop all existing schedulers
        for phone in list(self._schedulers.keys()):
            self.stop_account(phone)

        # Reschedule all accounts with the new configuration
        for account in config.telegram.account:
            if account.enabled and account.checkiner:
                scheduler = self.schedule_account(account)
                self._pool.add(scheduler.schedule())

        logger.info("已根据新的配置重新安排所有签到任务.")

    def _handle_account_change(self, added: List[TelegramAccount], removed: List[TelegramAccount]):
        """Handle account additions and removals"""
        for account in removed:
            self.stop_account(account.phone)
            logger.info(f"{account.phone} 账号的签到及其计划任务已被清除.")

        for account in added:
            scheduler = self.schedule_account(account)
            self._pool.add(scheduler.schedule())
            logger.info(f"新增的 {account.phone} 账号的计划任务已增加.")

    def stop_account(self, phone: str):
        """Stop scheduling and running tasks for an account"""
        # Cancel main checkin task
        if phone in self._tasks:
            self._tasks[phone].cancel()
            del self._tasks[phone]

        # Cancel all site-specific tasks
        if phone in self._site_tasks:
            for task in self._site_tasks[phone].values():
                task.cancel()
            del self._site_tasks[phone]

        # Cancel main account scheduler
        if phone in self._schedulers:
            del self._schedulers[phone]

        # Cancel all independent site schedulers for this account
        keys_to_remove = []
        for key in self._schedulers.keys():
            if key.startswith(f"{phone}."):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._schedulers[key]

    def _has_independent_time_range(self, site_name: str, config_to_use) -> bool:
        """Check if a site has independent time_range configuration"""
        site_config = config_to_use.get_site_config(site_name)
        return isinstance(site_config, dict) and "time_range" in site_config

    def _schedule_independent_sites(self, account: TelegramAccount, config_to_use):
        """Schedule sites with independent time_range configurations"""
        from .dynamic import get_cls, get_names, extract

        # Get checkin classes based on account config or global config
        site = None
        if account.site and account.site.checkiner is not None:
            site = account.site.checkiner
        elif config.site and config.site.checkiner is not None:
            site = config.site.checkiner
        else:
            site = get_names("checkiner")

        clses: List[Type[BaseBotCheckin]] = extract(get_cls("checkiner", names=site))

        for cls in clses:
            if hasattr(cls, "templ_name"):
                site_name = cls.templ_name
            else:
                site_name = cls.__module__.rsplit(".", 1)[-1]

            if self._has_independent_time_range(site_name, config_to_use):
                self._schedule_independent_site(account, site_name, config_to_use)

    def _schedule_independent_site(self, account: TelegramAccount, site_name: str, config_to_use):
        """Schedule a site with independent time_range configuration"""
        site_config = config_to_use.get_site_config(site_name)
        site_time_range = site_config.get("time_range")
        site_interval_days = site_config.get("interval_days", config_to_use.interval_days)

        phone_masked = TelegramAccount.get_phone_masked(account.phone)

        def on_next_time(t: datetime):
            logger.info(f"下一次 \"{phone_masked}\" 账号 {site_name} 站点的签到将在 {t.strftime('%m-%d %H:%M %p')} 进行.")
            date_ctx = RunContext.get_or_create(f"checkiner.date.{t.strftime('%Y%m%d')}")
            account_ctx = RunContext.get_or_create(f"checkiner.account.{account.phone}")
            site_ctx = RunContext.get_or_create(f"checkiner.site.{site_name}")
            return RunContext.prepare(
                description=f"{account.phone} 账号 {site_name} 站点签到",
                parent_ids=[account_ctx.id, date_ctx.id, site_ctx.id],
            )

        def func(ctx: RunContext):
            return asyncio.create_task(self._run_single_site(ctx, account, site_name))

        scheduler = Scheduler.from_str(
            func=func,
            interval_days=site_interval_days,
            time_range=site_time_range,
            on_next_time=on_next_time,
            description=f"{account.phone} 账号 {site_name} 站点签到定时任务",
            sid=f"checkiner.{account.phone}.{site_name}",
        )

        # Store scheduler with unique key
        scheduler_key = f"{account.phone}.{site_name}"
        self._schedulers[scheduler_key] = scheduler
        self._pool.add(scheduler.schedule())

    def schedule_account(self, account: TelegramAccount):
        """Schedule checkins for an account"""
        if (not account.checkiner) or (not account.enabled):
            return

        # Use account-specific config if available, otherwise use global
        config_to_use = account.checkiner_config or config.checkiner

        # Schedule sites with independent time_range configurations
        self._schedule_independent_sites(account, config_to_use)

        def on_next_time(t: datetime):
            phone_masked = TelegramAccount.get_phone_masked(account.phone)
            logger.info(f"下一次 \"{phone_masked}\" 账号的签到将在 {t.strftime('%m-%d %H:%M %p')} 进行.")
            date_ctx = RunContext.get_or_create(f"checkiner.date.{t.strftime('%Y%m%d')}")
            account_ctx = RunContext.get_or_create(f"checkiner.account.{account.phone}")
            return RunContext.prepare(
                description=f"{account.phone} 账号签到",
                parent_ids=[account_ctx.id, date_ctx.id],
            )

        def func(ctx: RunContext):
            if account.phone in self._tasks:
                self._tasks[account.phone].cancel()
                del self._tasks[account.phone]
            task = self._tasks[account.phone] = asyncio.create_task(self.run_account(ctx, account))
            return task

        scheduler = Scheduler.from_str(
            func=func,
            interval_days=config_to_use.interval_days,
            time_range=config_to_use.time_range,
            on_next_time=on_next_time,
            description=f"{account.phone} 每日签到定时任务",
            sid=f"checkiner.{account.phone}",
        )
        self._schedulers[account.phone] = scheduler
        return scheduler

    async def _task_main(self, checkiner: BaseBotCheckin, sem: asyncio.Semaphore, wait=0):
        if config.debug_cron:
            wait = 0.1
        if wait > 0:
            checkiner.log.debug(f"随机启动等待: 将等待 {wait:.2f} 分钟以启动.")
        await asyncio.sleep(wait * 60)
        async with sem:
            result = await checkiner._start()
            return checkiner, result

    async def run_account(self, ctx: RunContext, account: TelegramAccount, instant: bool = False):
        """Run checkin for a single account"""
        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                await self._run_account(ctx, a, client, instant)

    def schedule_site(
        self, ctx: RunContext, at: datetime, account: TelegramAccount, site: str, reschedule: bool = False
    ) -> asyncio.Task:
        try:
            account_ctx = RunContext.get_or_create(f"checkiner.account.{account.phone}")

            if reschedule:
                description = f"{account.phone} 账号 {site} 站点重新签到"
            else:
                description = f"{account.phone} 账号 {site} 站点签到"

            site_ctx = RunContext.prepare(description=description, parent_ids=[account_ctx.id, ctx.id])
            site_ctx.reschedule = (ctx.reschedule or 0) + 1

            async def _schedule():
                # 计算延迟时间(秒)
                delay = (at - datetime.now()).total_seconds()
                if delay > 0:
                    if reschedule:
                        logger.debug(
                            f"已安排账户 {account.phone} 的 {site} 站点在 {at.strftime('%m-%d %H:%M %p')} 重新尝试签到."
                        )
                    else:
                        logger.debug(
                            f"已安排账户 {account.phone} 的 {site} 站点在 {at.strftime('%m-%d %H:%M %p')} 签到."
                        )
                    await asyncio.sleep(delay)
                if account.phone in self._site_tasks and site in self._site_tasks[account.phone]:
                    self._site_tasks[account.phone][site].cancel()
                    del self._site_tasks[account.phone][site]
                await self._run_single_site(site_ctx, account, site)

            task = asyncio.create_task(_schedule())
            # Initialize _site_tasks for this phone if it doesn't exist
            if account.phone not in self._site_tasks:
                self._site_tasks[account.phone] = {}
            # Store the task
            self._site_tasks[account.phone][site] = task
            return task
        except Exception as e:
            if reschedule:
                logger.warning(f"重新安排 {site} 站点签到时间失败: {e}")
            else:
                logger.warning(f"安排 {site} 站点签到时间失败: {e}")
            show_exception(e, regular=False)

    async def _run_single_site(self, ctx: RunContext, account: TelegramAccount, site_name: str):
        async with ClientsSession([account]) as clients:
            async for _, client in clients:
                cls = get_cls("checkiner", names=[site_name])[0]
                config_to_use = account.checkiner_config or config.checkiner

                c: BaseBotCheckin = cls(
                    client,
                    context=ctx,
                    retries=config_to_use.retries,
                    timeout=config_to_use.timeout,
                    config=config_to_use.get_site_config(site_name),
                )

                log = logger.bind(username=client.me.full_name, name=c.name)

                result = await c._start()
                if result.status == RunStatus.SUCCESS:
                    log.info("重新签到成功.")
                elif result.status == RunStatus.NONEED:
                    log.info("多次重新签到后依然为已签到状态, 已跳过.")
                elif result.status == RunStatus.RESCHEDULE:
                    if c.ctx.next_time:
                        log.debug("继续等待重新签到.")
                        self.schedule_site(ctx, c.ctx.next_time, account, site_name, reschedule=True)
                else:
                    log.debug("站点重新签到失败.")

    async def _run_account(
        self, ctx: RunContext, account: TelegramAccount, client: Client, instant: bool = False
    ):
        """Run checkins for a single user"""
        log = logger.bind(username=client.me.full_name)

        # Get checkin classes based on account config or global config
        site = None
        if account.site and account.site.checkiner is not None:
            site = account.site.checkiner
        elif config.site and config.site.checkiner is not None:
            site = config.site.checkiner
        else:
            site = get_names("checkiner")

        clses: List[Type[BaseBotCheckin]] = extract(get_cls("checkiner", names=site))

        if not clses:
            if site is not None:  # Only show warning if sites were specified but none were valid
                log.warning("没有任何有效签到站点, 签到将跳过.")
            return

        log.warning("Auth Bot 不可用，已跳过 CHECKINER 总认证并直接启动签到站点。")

        config_to_use = account.checkiner_config or config.checkiner
        sem = asyncio.Semaphore(config_to_use.concurrency)
        checkiners = []
        for cls in clses:
            if hasattr(cls, "templ_name"):
                site_name = cls.templ_name
            else:
                site_name = cls.__module__.rsplit(".", 1)[-1]

            # Skip sites with independent time_range configurations
            if self._has_independent_time_range(site_name, config_to_use):
                log.debug(f"跳过站点 {site_name}, 该站点有独立的 time_range 配置")
                continue

            site_ctx = RunContext.prepare(f"{site_name} 站点签到", parent_ids=ctx.id)
            checkiners.append(
                cls(
                    client,
                    context=site_ctx,
                    retries=config_to_use.retries,
                    timeout=config_to_use.timeout,
                    config=config_to_use.get_site_config(site_name),
                )
            )

        tasks = []
        names = []
        for c in checkiners:
            names.append(c.name)
            wait = 0 if instant else random.uniform(0, config_to_use.random_start)
            task = self._task_main(c, sem, wait)
            tasks.append(task)

        if names:
            log.info(f'已启用签到器: {", ".join(names)}')

        results: List[Tuple[BaseBotCheckin, RunContext]] = await asyncio.gather(*tasks)

        failed = []
        ignored = []
        successful = []
        checked = []

        for c, result in results:
            if result.status == RunStatus.IGNORE:
                ignored.append(c.name)
            elif result.status == RunStatus.SUCCESS:
                successful.append(c.name)
            elif result.status == RunStatus.NONEED:
                checked.append(c.name)
            elif result.status == RunStatus.RESCHEDULE:
                if hasattr(c, "templ_name"):
                    site_name = c.templ_name
                else:
                    site_name = cls.__module__.rsplit(".", 1)[-1]
                if c.ctx.next_time:
                    self.schedule_site(ctx, c.ctx.next_time, account, site_name, reschedule=True)
                checked.append(c.name)
            else:
                failed.append(c.name)

        spec = f"共{len(successful) + len(checked) + len(failed) + len(ignored)}个"
        if successful:
            spec += f", {len(successful)}成功"
        if checked:
            spec += f", {len(checked)}已签到而跳过"
        if failed:
            spec += f", {len(failed)}失败"
        if ignored:
            spec += f", {len(ignored)}跳过"

        details = []
        if checked:
            details.append(f"已签到而跳过: {', '.join(checked)}")
        if failed:
            details.append(f"失败: {', '.join(failed)}")
        if ignored:
            details.append(f"跳过: {', '.join(ignored)}")

        if failed:
            msg = "签到部分失败" if successful else "签到失败"
            suffix = f": {'; '.join(details)}" if details else ""
            log.bind(log=True).error(f"{msg} ({spec}){suffix}")
        else:
            suffix = f": {'; '.join(details)}" if details else "."
            log.bind(log=True).info(f"签到成功 ({spec}){suffix}")

    def new_ctx(self):
        now = datetime.now()
        ctx = RunContext.get_or_create(
            f"checkiner.run.{now.timestamp()}",
            description=f"{now.strftime('%Y-%m-%d')} 签到",
        )
        return ctx

    async def run_all(self, instant: bool = False):
        """Run checkins for all enabled accounts without scheduling"""
        accounts = [a for a in config.telegram.account if a.enabled and a.checkiner]
        tasks = [
            asyncio.create_task(self.run_account(RunContext.prepare("运行全部签到器"), account, instant))
            for account in accounts
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def schedule_all(self):
        """Start scheduling checkins for all accounts"""

        for a in config.telegram.account:
            if a.enabled and a.checkiner:
                scheduler = self.schedule_account(a)
                self._pool.add(scheduler.schedule())

        if not self._schedulers:
            logger.info("没有需要执行的 Telegram 机器人签到任务")
            return None

        await self._pool.wait()
