from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Dict, Type
import random
import string
import re

from loguru import logger

from embykeeper.schedule import Scheduler
from embykeeper.schema import TelegramAccount
from embykeeper.config import config
from embykeeper.runinfo import RunContext, RunStatus
from embykeeper.utils import AsyncTaskPool

from .pyrogram import Client
from .embyboss import EmbybossRegister
from .dynamic import extract, get_cls
from .link import Link
from .session import ClientsSession

logger = logger.bind(scheme="teleregistrar")


class RegisterManager:
    """注册管理器"""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}  # phone -> task
        self._schedulers: Dict[str, Scheduler] = {}  # phone -> scheduler
        self._pool = AsyncTaskPool()

        config.on_list_change("telegram.account", self._handle_account_change)
        config.on_change("registrar", self._handle_config_change)

    def _handle_config_change(self, *args):
        """Handle changes to the register configuration"""
        # Stop all existing schedulers - collect phones first
        phones = set()
        for key in self._schedulers.keys():
            if "." in key:
                phone = key.split(".")[0]
                phones.add(phone)

        for phone in phones:
            self.stop_account(phone)

        # Reschedule all accounts with the new configuration
        for account in config.telegram.account:
            if account.enabled and account.registrar:
                schedulers = self.schedule_account(account)
                if schedulers:
                    if isinstance(schedulers, list):
                        for scheduler in schedulers:
                            if hasattr(scheduler, "schedule"):
                                self._pool.add(scheduler.schedule())
                    else:
                        # 间隔注册返回的是task, 直接添加
                        self._pool.add(schedulers)

        logger.info("已根据新的配置重新安排所有注册任务.")

    def _handle_account_change(self, added: List[TelegramAccount], removed: List[TelegramAccount]):
        """Handle account additions and removals"""
        for account in removed:
            self.stop_account(account.phone)
            logger.info(f"{account.phone} 账号的注册及其计划任务已被清除.")

        for account in added:
            if account.enabled and account.registrar:
                schedulers = self.schedule_account(account)
                if schedulers:
                    if isinstance(schedulers, list):
                        for scheduler in schedulers:
                            if hasattr(scheduler, "schedule"):
                                self._pool.add(scheduler.schedule())
                    else:
                        # 间隔注册返回的是task, 直接添加
                        self._pool.add(schedulers)
                    logger.info(f"新增的 {account.phone} 账号的注册计划任务已增加.")

    def stop_account(self, phone: str):
        """Stop scheduling and running tasks for an account"""
        # Cancel all tasks for this phone
        keys_to_remove = []
        for key in self._tasks.keys():
            if key.startswith(f"{phone}."):
                self._tasks[key].cancel()
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._tasks[key]

        # Cancel all schedulers for this phone
        keys_to_remove = []
        for key in self._schedulers.keys():
            if key.startswith(f"{phone}."):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._schedulers[key]

    def get_sites_for_account(self, account: TelegramAccount) -> List[str]:
        """获取账户需要注册的站点列表."""
        phone_masked = TelegramAccount.get_phone_masked(account.phone)

        sites = []
        if account.site and account.site.registrar:
            sites = account.site.registrar
        elif config.site and config.site.registrar:
            sites = config.site.registrar

        if not sites:
            logger.warning(f"{phone_masked} 账号未配置 registrar 站点, 将跳过注册调度")
            return []

        return sites

    def schedule_account(self, account: TelegramAccount) -> tuple[List[Scheduler], List[asyncio.Task]]:
        """为单个账户安排注册任务"""
        phone = account.phone
        if phone in self._schedulers or phone in self._tasks:
            self.stop_account(phone)

        # 获取此账户启用的站点
        sites_to_register_names = self.get_sites_for_account(account)
        if not sites_to_register_names:
            return [], []

        clses = extract(get_cls("registrar", names=sites_to_register_names))
        if not clses:
            logger.warning(f"{account.phone} 账号没有有效的registrar站点, 将跳过注册调度")
            return [], []

        schedulers = []
        tasks = []
        for cls in clses:
            if hasattr(cls, "templ_name"):
                site_name = cls.templ_name  # "templ_a<XiguaEmbyBot>"
            else:
                site_name = cls.__module__.rsplit(".", 1)[-1]

            site_config = config.registrar.get_site_config(site_name)
            if not site_config:
                logger.warning(f"{account.phone} 账号的站点 {site_name} 未配置注册设置, 将跳过")
                continue

            if site_config.get("times"):
                # 定时模式
                scheduler = self._schedule_site_timed(account, site_name, site_config)
                schedulers.append(scheduler)
            elif site_config.get("interval_minutes"):
                # 间隔模式
                task = self._schedule_site_interval(account, site_name, site_config)
                tasks.append(task)

        return schedulers, tasks

    def _schedule_site_timed(self, account: TelegramAccount, site_name: str, site_config: dict):
        """定时注册模式"""
        phone_masked = TelegramAccount.get_phone_masked(account.phone)
        times = site_config.get("times", [])

        # 将时间列表转换为时间范围格式
        times_str = ",".join(times)
        time_range = f"<{times_str}>"

        def on_next_time(t: datetime):
            logger.info(
                f"下一次 \"{phone_masked}\" 账号 {site_name} 站点的注册将在 {t.strftime('%m-%d %H:%M %p')} 进行."
            )
            date_ctx = RunContext.get_or_create(f"registrar.date.{t.strftime('%Y%m%d')}")
            account_ctx = RunContext.get_or_create(f"registrar.account.{account.phone}")
            site_ctx = RunContext.get_or_create(f"registrar.site.{site_name}")
            return RunContext.prepare(
                description=f"{account.phone} 账号 {site_name} 站点定时注册",
                parent_ids=[account_ctx.id, date_ctx.id, site_ctx.id],
            )

        def func(ctx: RunContext):
            task = asyncio.create_task(self._run_single_site(ctx, account, site_name, site_config))
            log = logger.bind(username=f"@{site_name}", name=f"{phone_masked}")
            log.info(f"已计划定时抢注任务, 下次运行: {scheduler.next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            return task

        scheduler = Scheduler.from_str(
            func=func,
            interval_days="1",  # 每天执行
            time_range=time_range,
            on_next_time=on_next_time,
            description=f"{account.phone} 账号 {site_name} 站点定时注册任务",
            sid=f"registrar.timed.{account.phone}.{site_name}",
        )

        scheduler_key = f"{account.phone}.{site_name}"
        self._schedulers[scheduler_key] = scheduler
        return scheduler

    def _schedule_site_interval(self, account: TelegramAccount, site_name: str, site_config: dict):
        """间隔注册模式"""
        interval_minutes = site_config.get("interval_minutes")
        task_key = f"{account.phone}.{site_name}"

        if interval_minutes < 3:
            # 连续模式
            task = asyncio.create_task(self._continuous_register_task(account, site_name, site_config))
        else:
            # 间隔模式
            task = asyncio.create_task(
                self._interval_register_task(account, site_name, site_config, interval_minutes)
            )

        self._tasks[task_key] = task
        return task

    async def _continuous_register_task(self, account: TelegramAccount, site_name: str, site_config: dict):
        """连续注册任务"""
        interval_minutes = site_config.get("interval_minutes")

        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                match = re.match(r"templ_a<(.+?)>", site_name)
                if not match:
                    logger.error(f"无法从 {site_name} 中提取机器人用户名")
                    return
                bot_username = match.group(1)

                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")
                log.info(f"开始连续注册, 间隔 {interval_minutes} 分钟.")

                if not await Link(client).auth("registrar", log_func=log.error):
                    log.error("账户权限验证失败.")
                    return

                embyboss_register = EmbybossRegister(
                    client=client,
                    logger=log,
                    username=client.me.username or f"user_{client.me.id}",
                    password="".join(random.choices(string.ascii_letters + string.digits, k=4)),
                )

                async def long_running_task():
                    try:
                        await embyboss_register.run_continuous(bot_username, interval_minutes * 60)
                    except asyncio.CancelledError:
                        log.info("连续注册任务被取消.")
                    except Exception as e:
                        log.error(f"连续注册任务出现异常: {e}")
                        logger.exception("详细异常信息:")

                task = asyncio.create_task(long_running_task())
                client.stop_handlers.append(task.cancel)
                try:
                    await task
                finally:
                    if task.cancel in client.stop_handlers:
                        client.stop_handlers.remove(task.cancel)

    async def _interval_register_task(
        self, account: TelegramAccount, site_name: str, site_config: dict, interval_minutes: int
    ):
        """间隔注册任务"""

        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                match = re.match(r"templ_a<(.+?)>", site_name)
                bot_username = match.group(1) if match else site_name

                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")

                async def loop():
                    while True:
                        try:
                            account_ctx = RunContext.get_or_create(f"registrar.account.{account.phone}")
                            await RunContext.run(
                                lambda c: self._run_single_site(c, account, site_name, site_config),
                                description=f"{account.phone} 账号 {site_name} 站点间隔注册",
                                parent_ids=[account_ctx.id],
                            )
                        except Exception as e:
                            log.error(f"间隔注册任务异常: {e}")
                            logger.exception("详细异常信息:")

                        await asyncio.sleep(interval_minutes * 60)

                task = asyncio.create_task(loop())
                client.stop_handlers.append(task.cancel)
                try:
                    await task
                finally:
                    if task.cancel in client.stop_handlers:
                        client.stop_handlers.remove(task.cancel)

    async def _run_single_site(
        self, ctx: RunContext, account: TelegramAccount, site_name: str, site_config: dict
    ):
        """运行单个站点的注册任务"""

        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                match = re.match(r"templ_a<(.+?)>", site_name)
                bot_username = match.group(1) if match else site_name

                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")

                if not await Link(client).auth("registrar", log_func=log.error):
                    log.error("账户权限验证失败.")
                    return

                clses = extract(get_cls("registrar", names=[site_name]))
                if not clses:
                    log.error(f"无法找到站点 {site_name} 的注册器")
                    return

                cls = clses[0]
                registrar = cls(client=client, **site_config)
                await registrar.start()

    async def schedule_all(self) -> tuple[List[Scheduler], List[asyncio.Task]]:
        """安排所有注册任务."""
        logger.debug(f"开始为所有账户安排注册任务, 总账户数: {len(config.telegram.account)}")

        all_schedulers = []
        all_tasks = []

        for a in config.telegram.account:
            logger.debug(
                f"检查账户 {a.phone}: enabled={a.enabled}, registrar={getattr(a, 'registrar', False)}"
            )
            if a.enabled and getattr(a, "registrar", False):
                logger.debug(f"为账户 {a.phone} 安排注册任务")
                schedulers_for_account, tasks_for_account = self.schedule_account(a)
                all_schedulers.extend(schedulers_for_account)
                all_tasks.extend(tasks_for_account)

        logger.debug(f"最终调度器数量: {len(all_schedulers)}, 任务数量: {len(all_tasks)}")
        return all_schedulers, all_tasks

    async def start(self):
        """安排所有注册任务并等待常驻任务完成."""
        schedulers, tasks = await self.schedule_all()

        if not schedulers and not tasks:
            logger.info("没有需要执行的 Telegram 机器人注册任务")
            return

        logger.info(f"已创建 {len(schedulers)} 个定时注册调度器和 {len(tasks)} 个间隔注册任务.")

        awaitables = tasks + [s.schedule() for s in schedulers]

        if awaitables:
            await asyncio.gather(*awaitables)

    async def _interval_register_task(
        self, account: TelegramAccount, site_name: str, site_config: dict, interval_minutes: int
    ):
        phone_masked = TelegramAccount.get_phone_masked(account.phone)

        async with ClientsSession([account]) as clients:
            async for _, client in clients:
                match = re.match(r"templ_a<(.+?)>", site_name)
                bot_username = match.group(1) if match else site_name

                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")

                async def loop():
                    while True:
                        try:
                            account_ctx = RunContext.get_or_create(f"register.account.{account.phone}")
                            site_ctx = RunContext.get_or_create(f"register.site.{site_name}")
                            ctx = RunContext.prepare(
                                description=f"{client.me.full_name} 账号 {site_name} 站点间隔注册",
                                parent_ids=[account_ctx.id, site_ctx.id],
                            )

                            await self._run_single_site(ctx, account, site_name, site_config)
                            await asyncio.sleep(interval_minutes * 60)

                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.error(f"{phone_masked} 账号 {site_name} 站点注册异常: {e}")
                            await asyncio.sleep(interval_minutes * 60)

                task = asyncio.create_task(loop())
                client.stop_handlers.append(task.cancel)
                try:
                    await task
                finally:
                    if task.cancel in client.stop_handlers:
                        client.stop_handlers.remove(task.cancel)

    async def run_account(self, ctx: RunContext, account: TelegramAccount, instant: bool = False):
        """Run register for a single account"""
        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                await self._run_account(ctx, a, client, instant)

    async def _run_single_site(
        self, ctx: RunContext, account: TelegramAccount, site_name: str, site_config: dict
    ):
        """运行单个站点的注册"""
        async with ClientsSession([account]) as clients:
            async for _, client in clients:
                match = re.match(r"templ_a<(.+?)>", site_name)
                bot_username = match.group(1) if match else site_name

                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")

                if not await Link(client).auth("registrar", log_func=log.error):
                    return

                cls = get_cls("registrar", names=[site_name])[0]

                register = cls(
                    client,
                    context=ctx,
                    retries=site_config.get("retries", 1),
                    timeout=site_config.get("timeout", 120),
                    config=site_config,
                )

                result = await register._start()
                if result.status == RunStatus.SUCCESS:
                    logger.bind(username=f"@{site_name}", name=f"{client.me.full_name}").info("注册成功")
                elif result.status == RunStatus.IGNORE:
                    logger.bind(username=f"@{site_name}", name=f"{client.me.full_name}").info("跳过注册")
                else:
                    logger.bind(username=f"@{site_name}", name=f"{client.me.full_name}").warning("注册失败")

    async def _run_account(
        self, ctx: RunContext, account: TelegramAccount, client: Client, instant: bool = False
    ):
        """Run registers for a single user"""
        log = logger.bind(username=client.me.full_name)

        # Get register classes based on account config or global config
        site = None
        if account.site and account.site.registrar is not None:
            site = account.site.registrar
        elif config.site and config.site.registrar is not None:
            site = config.site.registrar
        else:
            log.warning("没有配置registrar站点, 注册将跳过.")
            return

        clses: List[Type] = extract(get_cls("registrar", names=site))

        if not clses:
            log.warning("没有任何有效注册站点, 注册将跳过.")
            return

        if not await Link(client).auth("registrar", log_func=log.error):
            return

        config_to_use = account.registrar_config or config.registrar
        sem = asyncio.Semaphore(config_to_use.concurrency)
        registers = []

        for cls in clses:
            if hasattr(cls, "templ_name"):
                site_name = cls.templ_name
            else:
                site_name = cls.__module__.rsplit(".", 1)[-1]

            site_config = config_to_use.get_site_config(site_name)
            if not site_config:
                log.warning(f"站点 {site_name} 未配置注册设置, 将跳过")
                continue

            site_ctx = RunContext.prepare(f"{site_name} 站点注册", parent_ids=ctx.id)
            registers.append(
                cls(
                    client,
                    context=site_ctx,
                    retries=site_config.get("retries", 1),
                    timeout=site_config.get("timeout", 120),
                    config=site_config,
                )
            )

        if not registers:
            log.warning("所有站点都未正确配置, 注册将跳过.")
            return

        tasks = []
        names = []
        for r in registers:
            names.append(f"@{r.bot_username}" if hasattr(r, "bot_username") and r.bot_username else r.name)
            task = self._task_main(r, sem)
            tasks.append(task)

        if names:
            logger.info(f'已启用注册器: {", ".join(names)}')

        results = await asyncio.gather(*tasks)

        failed = []
        successful = []
        ignored = []

        for r, result in results:
            if result.status == RunStatus.SUCCESS:
                successful.append(r.name)
            elif result.status == RunStatus.IGNORE:
                ignored.append(r.name)
            else:
                failed.append(r.name)

        spec = f"共{len(successful) + len(failed) + len(ignored)}个"
        if successful:
            spec += f", {len(successful)}成功"
        if failed:
            spec += f", {len(failed)}失败"
        if ignored:
            spec += f", {len(ignored)}跳过"

        if failed:
            msg = "注册部分失败" if successful else "注册失败"
            logger.bind(username=client.me.full_name).error(f"{msg} ({spec}): {', '.join(failed)}")
        else:
            logger.bind(username=client.me.full_name).info(f"注册完成 ({spec}).")

    async def _task_main(self, register, sem: asyncio.Semaphore):
        # 注册器不需要等待, 立即执行
        async with sem:
            result = await register._start()
            return register, result

    async def run_all(self, instant: bool = False):
        """Run registers for all enabled accounts without scheduling"""
        accounts = [a for a in config.telegram.account if a.enabled and getattr(a, "registrar", False)]
        tasks = [
            asyncio.create_task(self.run_account(RunContext.prepare("运行全部注册器"), account, instant))
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

    async def run_single_bot(self, bot_username: str, instant: bool = True):
        """快速注册单个bot - 用于-R命令"""
        accounts = [a for a in config.telegram.account if a.enabled]

        if not accounts:
            logger.error("没有可用的Telegram账号")
            return

        # 为每个账号创建快速注册任务
        tasks = []
        for account in accounts:
            task = asyncio.create_task(self._run_single_bot_for_account(account, bot_username))
            tasks.append(task)

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _run_single_bot_for_account(self, account: TelegramAccount, bot_username: str):
        async with ClientsSession([account]) as clients:
            async for a, client in clients:
                log = logger.bind(name=f"{client.me.full_name}, @{bot_username}")

                if not await Link(client).auth("registrar", log_func=log.error):
                    return

                embyboss_register = EmbybossRegister(
                    client=client,
                    logger=log,
                    username=client.me.username or f"user_{client.me.id}",
                    password="".join(random.choices(string.ascii_letters + string.digits, k=4)),
                )

                task = asyncio.create_task(embyboss_register.run_continuous(bot_username, 1))
                client.stop_handlers.append(task.cancel)
                try:
                    await task
                finally:
                    if task.cancel in client.stop_handlers:
                        client.stop_handlers.remove(task.cancel)
                logger.bind(name=f"{client.me.full_name}, @{bot_username}").info("快速抢注任务已完成.")
