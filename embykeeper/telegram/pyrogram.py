from __future__ import annotations

import base64
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
import inspect
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
from typing import Union
import logging

from rich.prompt import Prompt
from loguru import logger
import pyrogram
from pyrogram import raw, types, filters, dispatcher
from pyrogram.enums import SentCodeType
from pyrogram.errors import (
    BadRequest,
    SessionPasswordNeeded,
    CodeInvalid,
    PhoneCodeInvalid,
    FloodWait,
    PhoneNumberInvalid,
    PhoneNumberBanned,
    MessageIdInvalid,
)
from pyrogram.handlers import (
    MessageHandler,
    RawUpdateHandler,
    DisconnectHandler,
    EditedMessageHandler,
    StartHandler,
    StopHandler,
    ConnectHandler,
)
from pyrogram.storage.sqlite_storage import SQLiteStorage, TEST, PROD
from pyrogram.handlers.handler import Handler

from embykeeper import var, __name__ as __product__, __version__
from embykeeper.schema import TelegramAccount
from embykeeper.utils import async_partial, show_exception

var.tele_used.set()

logger = logger.bind(scheme="telegram", nonotify=True)


class LogRedirector(logging.StreamHandler):
    def emit(self, record):
        try:
            if record.levelno >= logging.WARNING:
                logger.debug(f"Pyrogram 警告: {record.getMessage()}")
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


pyrogram_session_logger = logging.getLogger("pyrogram")
for h in pyrogram_session_logger.handlers[:]:
    pyrogram_session_logger.removeHandler(h)
pyrogram_session_logger.addHandler(LogRedirector())


class Dispatcher(dispatcher.Dispatcher):
    updates_count = 0

    def __init__(self, client: Client):
        super().__init__(client)
        self.mutex = asyncio.Lock()

    async def start(self):
        phone_masked = TelegramAccount.get_phone_masked(self.client.phone_number)
        logger.debug(f'Telegram 更新分配器正在启动: "{phone_masked}".')

        if callable(self.client.start_handler):
            try:
                await self.client.start_handler(self.client)
            except Exception as e:
                show_exception(e, regular=False)
                logger.error("Telegram 更新分配器启动错误.")

        if not self.client.no_updates:
            for _ in range(self.client.workers):
                self.handler_worker_tasks.append(self.client.loop.create_task(self.handler_worker()))

            if not self.client.skip_updates:
                await self.client.recover_gaps()

        logger.debug(f'Telegram 更新分配器已启动: "{phone_masked}".')

    async def stop(self, clear_handlers: bool = True):
        phone_masked = TelegramAccount.get_phone_masked(self.client.phone_number)
        logger.debug(f'Telegram 更新分配器正在停止: "{phone_masked}".')

        if callable(self.client.stop_handler):
            try:
                await self.client.stop_handler(self.client)
            except Exception as e:
                show_exception(e, regular=False)
                logger.error("Telegram 更新分配器停止错误.")

        if not self.client.no_updates:
            for i in range(self.client.workers):
                self.updates_queue.put_nowait(None)

            for i in self.handler_worker_tasks:
                i.cancel()
                try:
                    await i
                except asyncio.CancelledError:
                    pass
            if clear_handlers:
                self.handler_worker_tasks.clear()
                self.groups.clear()

        logger.debug(f'Telegram 更新分配器已停止: "{phone_masked}".')

    def add_handler(self, handler, group: int):
        async def fn():
            async with self.mutex:
                if group not in self.groups:
                    self.groups[group] = []
                    self.groups = OrderedDict(sorted(self.groups.items()))
                self.groups[group].append(handler)
                # logger.debug(f"增加了 Telegram 更新处理器: {handler.__class__.__name__}.")

        return self.client.loop.create_task(fn())

    def remove_handler(self, handler, group: int):
        async def fn():
            async with self.mutex:
                if group not in self.groups:
                    raise ValueError(f"Group {group} does not exist. Handler was not removed.")
                self.groups[group].remove(handler)
                # logger.debug(f"移除了 Telegram 更新处理器: {handler.__class__.__name__}.")

        return self.client.loop.create_task(fn())

    async def handler_worker(self):
        while True:
            packet = await self.updates_queue.get()
            Dispatcher.updates_count += 1

            if packet is None:
                break

            try:
                update, users, chats = packet
                parser = self.update_parsers.get(type(update), None)

                try:
                    parsed_update, handler_type = (
                        await parser(update, users, chats) if parser is not None else (None, type(None))
                    )
                except (ValueError, BadRequest) as e:
                    logger.warning(f"更新处理器发生错误, 可能遗漏消息.")
                    show_exception(e, regular=False)
                    continue

                async with self.mutex:
                    groups = {i: g[:] for i, g in self.groups.items()}

                for group in groups.values():
                    for handler in group:
                        args = None

                        if isinstance(handler, handler_type):
                            try:
                                if await handler.check(self.client, parsed_update):
                                    args = (parsed_update,)
                            except Exception as e:
                                logger.warning(f"更新处理器发生错误, 可能遗漏消息.")
                                show_exception(e, regular=False)
                                continue

                        elif isinstance(handler, RawUpdateHandler):
                            try:
                                if await handler.check(self.client, update):
                                    args = (update, users, chats)
                            except Exception as e:
                                logger.warning(f"更新处理器发生错误, 可能遗漏消息.")
                                show_exception(e, regular=False)
                                continue

                        if args is None:
                            continue

                        try:
                            if inspect.iscoroutinefunction(handler.callback):
                                await handler.callback(self.client, *args)
                            else:
                                await self.client.loop.run_in_executor(
                                    self.client.executor, handler.callback, self.client, *args
                                )
                        except pyrogram.StopPropagation:
                            raise
                        except pyrogram.ContinuePropagation:
                            continue
                        except Exception as e:
                            logger.error(f"更新回调函数内发生错误.")
                            show_exception(e, regular=False)
                        break
                    else:
                        continue
                    break
            except pyrogram.StopPropagation:
                pass
            except Exception as e:
                logger.warning("更新控制器错误.")
                show_exception(e, regular=False)


class FileStorage(SQLiteStorage):
    async def open(self):
        path = self.database
        file_exists = path.is_file()

        # Try to create database in the original path
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), timeout=1, check_same_thread=False)
        except sqlite3.OperationalError as e:
            if "unable to open database file" in str(e):
                # Test write permission by trying to create a temporary file
                test_error = None
                try:
                    test_file = path.parent / f".{self.name}_test"
                    test_file.write_text("test")
                    test_file.unlink()
                except Exception as write_e:
                    test_error = str(write_e)

                error_msg = f"无法在默认路径创建数据库文件 {path}: {e}"
                if test_error:
                    error_msg += f" (写入测试失败: {test_error})"
                else:
                    error_msg += " (目录可写, 可能是 SQLite 特定问题)"

                logger.warning(error_msg)

                # Fallback to system temp directory
                temp_dir = Path(tempfile.gettempdir())
                temp_path = temp_dir / (self.name + self.FILE_EXTENSION)

                logger.info(f"尝试在临时目录创建会话文件: {temp_path}")

                try:
                    self.conn = sqlite3.connect(str(temp_path), timeout=1, check_same_thread=False)
                    # Update the database path to the new location
                    self.database = temp_path
                    path = temp_path
                    file_exists = temp_path.is_file()
                    logger.info(f"成功在临时目录创建会话文件: {temp_path}")
                except sqlite3.OperationalError as temp_e:
                    logger.error(f"无法创建数据库文件: {temp_e}")
                    raise temp_e
            else:
                raise

        if self.use_wal:
            self.conn.execute("PRAGMA journal_mode=WAL")
        else:
            self.conn.execute("PRAGMA journal_mode=DELETE")

        # Check if database has required tables before calling update
        database_is_valid = False
        if file_exists:
            try:
                # Try to check if version table exists
                cursor = self.conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='version';")
                if cursor.fetchone():
                    database_is_valid = True
                cursor.close()
            except sqlite3.Error:
                # Database is corrupted or incomplete
                database_is_valid = False

        if not file_exists or not database_is_valid:
            if file_exists and not database_is_valid:
                logger.debug(f"数据库文件结构不完整, 重新初始化: {path}")
            await self.create()
            if self.session_string:
                # Old format
                if len(self.session_string) in [self.SESSION_STRING_SIZE, self.SESSION_STRING_SIZE_64]:
                    dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
                        (
                            self.OLD_SESSION_STRING_FORMAT
                            if len(self.session_string) == self.SESSION_STRING_SIZE
                            else self.OLD_SESSION_STRING_FORMAT_64
                        ),
                        base64.urlsafe_b64decode(self.session_string + "=" * (-len(self.session_string) % 4)),
                    )

                    await self.dc_id(dc_id)
                    await self.test_mode(test_mode)
                    await self.auth_key(auth_key)
                    await self.user_id(user_id)
                    await self.is_bot(is_bot)
                    await self.date(0)

                    logger.warning(
                        "You are using an old session string format. Use export_session_string to update"
                    )
                    return

                dc_id, api_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
                    self.SESSION_STRING_FORMAT,
                    base64.urlsafe_b64decode(self.session_string + "=" * (-len(self.session_string) % 4)),
                )

                await self.dc_id(dc_id)

                if test_mode:
                    await self.server_address(TEST[dc_id])
                    await self.port(80)
                else:
                    await self.server_address(PROD[dc_id])
                    await self.port(443)

                await self.api_id(api_id)
                await self.test_mode(test_mode)
                await self.auth_key(auth_key)
                await self.user_id(user_id)
                await self.is_bot(is_bot)
                await self.date(0)
        else:
            await self.update()

        with self.conn:
            self.conn.execute("VACUUM")

    async def delete(self):
        try:
            os.remove(self.database)
        except FileNotFoundError:
            logger.debug(f"会话文件已不存在: {self.database}")
        except OSError as e:
            logger.warning(f"删除会话文件失败: {self.database}, 错误: {e}")
            raise


class Client(pyrogram.Client):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        if self.in_memory:
            self.storage = SQLiteStorage(
                self.name, workdir=self.workdir, session_string=self.session_string, in_memory=self.in_memory
            )
        else:
            self.storage = FileStorage(
                self.name, workdir=self.workdir, session_string=self.session_string, in_memory=self.in_memory
            )

        self.dispatcher: Dispatcher = Dispatcher(self)

        self.stop_handlers = []

    async def authorize(self):
        if self.bot_token:
            return await self.sign_in_bot(self.bot_token)
        retry = False
        sent_code = await self.send_code(self.phone_number)
        code_target = {
            SentCodeType.APP: " Telegram 客户端",
            SentCodeType.SMS: "短信",
            SentCodeType.CALL: "来电",
            SentCodeType.FLASH_CALL: "闪存呼叫",
            SentCodeType.FRAGMENT_SMS: " Fragment 短信",
            SentCodeType.EMAIL_CODE: "邮件",
        }

        attempts = 0
        while True:
            try:
                if not self.phone_code:
                    if retry:
                        msg = f'验证码错误, 请重新输入 "{self.phone_number}" 的登录验证码 (按回车确认)'
                    else:
                        msg = f'请从{code_target[sent_code.type]}接收 "{self.phone_number}" 的登录验证码 (按回车确认)'
                    try:
                        self.phone_code = Prompt.ask(" " * 23 + msg, console=var.console)
                    except EOFError:
                        raise BadRequest(
                            f'登录 "{self.phone_number}" 时出现异常: 您正在使用非交互式终端, 无法输入验证码.'
                        )
                signed_in = await self.sign_in(self.phone_number, sent_code.phone_code_hash, self.phone_code)
            except (CodeInvalid, PhoneCodeInvalid):
                self.phone_code = None
                retry = True
                attempts += 1
                if attempts >= 3:
                    raise BadRequest(
                        f'登录 "{self.phone_number}" 时出现异常: 验证码尝试次数过多, 请稍后重试.'
                    )
                await asyncio.sleep(3)
            except SessionPasswordNeeded:
                retry = False
                while True:
                    if not self.password:
                        if retry:
                            msg = f'密码错误, 请重新输入 "{self.phone_number}" 的两步验证密码 (不显示, 按回车确认)'
                        else:
                            msg = f'需要输入 "{self.phone_number}" 的两步验证密码 (不显示, 按回车确认)'
                        self.password = Prompt.ask(" " * 23 + msg, password=True, console=var.console)
                    try:
                        return await self.check_password(self.password)
                    except BadRequest:
                        self.password = None
                        retry = True
            except FloodWait:
                raise BadRequest(f'登录 "{self.phone_number}" 时出现异常: 登录过于频繁.')
            except PhoneNumberInvalid:
                raise BadRequest(
                    f'登录 "{self.phone_number}" 时出现异常: 您使用了错误的手机号 (格式错误或没有注册).'
                )
            except PhoneNumberBanned:
                raise BadRequest(f'登录 "{self.phone_number}" 时出现异常: 您的账户已被封禁.')
            except Exception as e:
                logger.error(f"登录时出现异常错误!")
                show_exception(e, regular=False)
                retry = True
                attempts += 1
                if attempts >= 3:
                    raise BadRequest(f'登录 "{self.phone_number}" 时出现异常: 尝试次数过多, 请稍后重试.')
                await asyncio.sleep(3)
            else:
                break
        if isinstance(signed_in, types.User):
            return signed_in
        else:
            raise BadRequest("该账户尚未注册")

    def add_handler(self, handler: Handler, group: int = 0):
        async def dummy():
            pass

        if isinstance(handler, StartHandler):
            self.start_handler = handler.callback
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, StopHandler):
            self.stop_handler = handler.callback
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, ConnectHandler):
            self.connect_handler = handler.callback
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, DisconnectHandler):
            self.disconnect_handler = handler.callback
            return asyncio.ensure_future(dummy())
        else:
            return self.dispatcher.add_handler(handler, group)

    def remove_handler(self, handler: Handler, group: int = 0):
        async def dummy():
            pass

        if isinstance(handler, StartHandler):
            self.start_handler = None
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, StopHandler):
            self.stop_handler = None
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, ConnectHandler):
            self.connect_handler = None
            return asyncio.ensure_future(dummy())
        elif isinstance(handler, DisconnectHandler):
            self.disconnect_handler = None
            return asyncio.ensure_future(dummy())
        else:
            return self.dispatcher.remove_handler(handler, group)

    @asynccontextmanager
    async def catch_reply(self, chat_id: Union[int, str], outgoing=False, filter=None):
        async def handler_func(client, message, future: asyncio.Future):
            try:
                future.set_result(message)
            except asyncio.InvalidStateError:
                pass

        future = asyncio.Future()
        f = filters.chat(chat_id)
        if not outgoing:
            f = f & (~filters.outgoing)
        if filter:
            f = f & filter
        handler = MessageHandler(async_partial(handler_func, future=future), f)
        await self.add_handler(handler, group=0)
        try:
            yield future
        finally:
            await self.remove_handler(handler, group=0)

    @asynccontextmanager
    async def catch_edit(self, message: types.Message, filter=None):
        def filter_message(id: int):
            async def func(flt, _, message: types.Message):
                return message.id == id

            return filters.create(func, "MessageFilter")

        async def handler_func(client, message, future: asyncio.Future):
            try:
                future.set_result(message)
            except asyncio.InvalidStateError:
                pass

        future = asyncio.Future()
        f = filter_message(message.id)
        if filter:
            f = f & filter
        handler = EditedMessageHandler(async_partial(handler_func, future=future), f)
        await self.add_handler(handler, group=0)
        try:
            yield future
        finally:
            await self.remove_handler(handler, group=0)

    async def wait_reply(
        self,
        chat_id: Union[int, str],
        send: str = None,
        timeout: float = 10,
        filter=None,
    ):
        async with self.catch_reply(chat_id=chat_id, filter=filter) as f:
            if send:
                await self.send_message(chat_id, send)
            msg: types.Message = await asyncio.wait_for(f, timeout)
            return msg

    async def wait_edit(
        self,
        message: types.Message,
        click: Union[str, int] = None,
        timeout: float = 10,
        noanswer=True,
        filter=None,
    ):
        async with self.catch_edit(message, filter=filter) as f:
            if click:
                try:
                    await message.click(click)
                except (TimeoutError, MessageIdInvalid):
                    if noanswer:
                        pass
                    else:
                        raise
            msg: types.Message = await asyncio.wait_for(f, timeout)
            return msg

    async def mute_chat(self, chat_id: Union[int, str], until: Union[int, datetime, None] = None):
        if until is None:
            until = 0x7FFFFFFF  # permanent mute
        elif isinstance(until, datetime):
            until = until.timestamp()
        return await self.invoke(
            raw.functions.account.UpdateNotifySettings(
                peer=raw.types.InputNotifyPeer(peer=await self.resolve_peer(chat_id)),
                settings=raw.types.InputPeerNotifySettings(
                    show_previews=False,
                    mute_until=int(until),
                ),
            )
        )

    async def handle_updates(self, updates):
        try:
            return await super().handle_updates(updates)
        except OSError as e:
            logger.warning(f"与 Telegram 服务器连接错误: {e}")
            raise
        except sqlite3.ProgrammingError:
            return
