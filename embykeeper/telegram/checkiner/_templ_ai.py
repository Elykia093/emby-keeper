import asyncio
import base64
import mimetypes
import random
import re
from pathlib import Path
from typing import List, Optional, Union

from loguru import logger
from pydantic import BaseModel, ValidationError
from pyrogram.errors import MessageIdInvalid
from pyrogram.raw.types.messages import BotCallbackAnswer
from pyrogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
from thefuzz import process

from embykeeper.config import config
from embykeeper.utils import to_iterable, to_thread_compat

from . import BotCheckin
from ._templ_a import TemplateACheckin

__ignore__ = True


class TemplateAICheckinConfig(BaseModel):
    # fmt: off
    name: Optional[str] = None  # 签到器的名称
    use_button_answer: Optional[bool] = None  # 点击按钮后等待并识别响应
    bot_text_ignore_answer: Union[str, List[str], None] = None  # 忽略的响应文本
    bot_fail_keywords: Union[str, List[str], None] = None  # 签到错误将重试时检测的关键词
    bot_success_keywords: Union[str, List[str], None] = None  # 成功时检测的关键词
    bot_success_pat: Optional[str] = None  # 成功消息积分匹配模式
    bot_captcha_len: Optional[int] = None  # 验证码长度的可能范围
    bot_text_ignore: Union[str, List[str], None] = None  # 忽略的文本关键词
    bot_checkin_caption_pat: Optional[str] = None  # 验证码图片 caption 匹配 regex
    bot_checkin_cmd: Optional[str] = None  # 签到命令
    bot_use_captcha: Optional[bool] = None  # 是否将图片视为验证码
    bot_checkin_button: Union[str, List[str], None] = None  # 进入签到流程的按钮文本
    templ_panel_keywords: Union[str, List[str], None] = None  # 面板关键词
    api_key: Optional[str] = None  # 智谱 API Key
    model_id: Optional[str] = None  # 智谱图像模型 ID
    llm_prompt: Optional[str] = None  # 发送给图像模型的额外提示词
    llm_timeout: Optional[int] = None  # 图像模型超时时间
    llm_button_match_threshold: Optional[int] = None  # LLM 结果与按钮的最低匹配分数
    # fmt: on


class TemplateAICheckin(TemplateACheckin):
    model_id = "glm-4.1v-thinking-flashx"
    llm_timeout = 60
    llm_button_match_threshold = 70
    llm_prompt = "你在帮助 Telegram 签到。请根据图片中的验证码、图案、文字或题目，" "从候选按钮中选择唯一正确答案。"

    _zhipu_client = None
    _zhipu_api_key = None
    _zhipu_model_id = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._captcha_options_event = asyncio.Event()
        self._captcha_options_message: Optional[Message] = None

    async def init(self):
        if not await super().init():
            return False

        try:
            self.ai_config = TemplateAICheckinConfig.model_validate(self.config)
        except ValidationError as e:
            self.log.warning(f"初始化失败: 签到自定义模板 AI 的配置错误:\n{e}")
            return False

        global_ai_config = self.get_global_ai_config()
        self.api_key = self.ai_config.api_key or global_ai_config.get("api_key")
        self.model_id = self.ai_config.model_id or global_ai_config.get("model_id") or self.model_id
        self.llm_timeout = self.ai_config.llm_timeout or self.llm_timeout
        self.llm_button_match_threshold = (
            self.ai_config.llm_button_match_threshold or self.llm_button_match_threshold
        )
        if self.ai_config.llm_prompt:
            self.llm_prompt = self.ai_config.llm_prompt
        self._last_llm_response_preview = None

        self.log = logger.bind(scheme="telechecker", name=self.name, username=self.client.me.full_name)
        return True

    def get_global_ai_config(self):
        ai_config = getattr(config.checkiner, "ai", None) or {}
        if isinstance(ai_config, dict):
            return ai_config
        return {}

    async def message_handler(self, client, message: Message):
        text = message.caption or message.text
        if self.is_captcha_options_message(message, text):
            self.remember_captcha_options_message(message)
            self.log.debug("已缓存验证码按钮消息, 等待图片验证码到达.")
            return

        if (
            (not message.photo)
            and text
            and message.reply_markup
            and (
                (
                    self.templ_panel_keywords
                    and any(keyword in text for keyword in to_iterable(self.templ_panel_keywords))
                )
                or (getattr(message, "is_first_response", False) and not message.edit_date)
            )
        ):
            keys = [k.text for r in message.reply_markup.inline_keyboard for k in r]
            for k in keys:
                if any(btn in k for btn in self.bot_checkin_button):
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    try:
                        answer: BotCallbackAnswer = await message.click(k)
                    except TimeoutError:
                        self.log.debug("点击签到按钮无响应, 可能按钮未正确处理点击回复. 一般来说不影响签到.")
                    except MessageIdInvalid:
                        pass
                    else:
                        await self.on_button_answer(answer)
                    return
            else:
                self.log.warning("签到失败: 账户错误.")
                return await self.fail()

        if message.text and "请先点击下面加入我们的" in message.text:
            self.log.warning("签到失败: 账户错误.")
            return await self.fail()

        await BotCheckin.message_handler(self, client, message)

    async def on_photo(self, message: Message):
        option_message = message if self.get_keys(message) else await self.wait_for_captcha_options_message()
        options = self.get_keys(option_message) if option_message else []
        if not options:
            self.log.warning("签到失败: 未找到与验证码图片对应的可点击按钮消息.")
            return await self.fail()

        try:
            image = await self.client.download_media(message, in_memory=True)
        except Exception as e:
            self.log.warning(f"签到失败: 无法下载验证码图片: {e}.")
            return await self.retry()

        answer = await self.solve_with_llm(image, options)
        if not answer:
            self.log.warning(
                f"签到失败: 图像模型未返回可用答案, 候选按钮: {options}, "
                f"原始响应预览: {self._last_llm_response_preview or '<empty>'}, 正在重试."
            )
            return await self.retry()

        button = self.match_button(answer, options)
        if not button:
            self.log.warning(f'签到失败: 无法将图像模型结果 "{answer}" 匹配到按钮 {options}, 正在重试.')
            return await self.retry()

        self.log.info(f'图像模型已选择按钮: "{button}".')
        await asyncio.sleep(random.uniform(0.5, 1.5))
        try:
            result = await option_message.click(button)
        except (TimeoutError, MessageIdInvalid):
            self.log.warning(f'点击图像模型选择的按钮 "{button}" 后无响应或消息已失效.')
            return
        else:
            await self.on_captcha_button_answer(result)

    def get_keys(self, message: Message):
        reply_markup = message.reply_markup
        if isinstance(reply_markup, InlineKeyboardMarkup):
            return [k.text for r in reply_markup.inline_keyboard for k in r]
        elif isinstance(reply_markup, ReplyKeyboardMarkup):
            return [k.text for r in reply_markup.keyboard for k in r]
        return []

    def is_captcha_options_message(self, message: Message, text: Optional[str]) -> bool:
        if message.photo or not text or not message.reply_markup:
            return False

        options = self.get_keys(message)
        if not options:
            return False

        if self.templ_panel_keywords and any(
            keyword in text for keyword in to_iterable(self.templ_panel_keywords)
        ):
            return False

        if any(any(btn in option for btn in to_iterable(self.bot_checkin_button)) for option in options):
            return False

        prompt_keywords = (
            "验证码",
            "验证",
            "点击图片",
            "显示的数字",
            "请选择图片",
            "请选择正确",
            "第 1 步",
            "第 2 步",
        )
        if any(keyword in text for keyword in prompt_keywords):
            return True

        numeric_buttons = [option for option in options if re.fullmatch(r"\d+", option)]
        if len(numeric_buttons) >= max(3, len(options) // 2):
            return True

        return False

    def remember_captcha_options_message(self, message: Message):
        self._captcha_options_message = message
        self._captcha_options_event.set()

    def pop_captcha_options_message(self) -> Optional[Message]:
        message = self._captcha_options_message
        self._captcha_options_message = None
        self._captcha_options_event.clear()
        return message

    async def wait_for_captcha_options_message(self, timeout: float = 8) -> Optional[Message]:
        message = self.pop_captcha_options_message()
        if message:
            return message

        try:
            await asyncio.wait_for(self._captcha_options_event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return self.pop_captcha_options_message()

    async def solve_with_llm(self, image, options: List[str]) -> Optional[str]:
        client = self.get_zhipu_client()
        if not client:
            return None

        self._last_llm_response_preview = None
        prompt = self.build_prompt(options)
        image_url = self.encode_image(image)

        def run_request():
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
            )
            return response.choices[0].message.content

        try:
            content = await asyncio.wait_for(to_thread_compat(run_request), timeout=self.llm_timeout)
        except ImportError:
            self.log.warning("签到失败: 未安装 zai-sdk, 请先安装 `zai-sdk==0.2.2`.")
            return None
        except asyncio.TimeoutError:
            self.log.warning("签到失败: 图像模型请求超时.")
            return None
        except Exception as e:
            self.log.warning(f"签到失败: 图像模型请求失败: {e}.")
            return None

        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item) for item in content
            )
        self._last_llm_response_preview = (content or "").replace("\n", " ").strip()[:200] or "<empty>"
        answer = self.extract_answer(content)
        if answer:
            self.log.debug(f"图像模型返回答案: {answer}")
        return answer

    def get_zhipu_client(self):
        api_key = self.api_key
        if not api_key:
            self.log.warning("签到失败: 未设置智谱 API Key, 请在 `config.toml` 中配置 `[checkiner.ai].api_key`.")
            return None

        if (
            self.__class__._zhipu_client
            and self.__class__._zhipu_api_key == api_key
            and self.__class__._zhipu_model_id == self.model_id
        ):
            return self.__class__._zhipu_client

        try:
            from zai import ZhipuAiClient
        except ImportError:
            self.log.warning("签到失败: 未安装 zai-sdk, 请先安装 `zai-sdk==0.2.2`.")
            return None

        self.__class__._zhipu_client = ZhipuAiClient(api_key=api_key)
        self.__class__._zhipu_api_key = api_key
        self.__class__._zhipu_model_id = self.model_id
        return self.__class__._zhipu_client

    def build_prompt(self, options: List[str]) -> str:
        option_lines = "\n".join(f"- {option}" for option in options)
        prompt = self.llm_prompt.strip()
        if "{options}" in prompt:
            prompt = prompt.replace("{options}", option_lines)
        else:
            prompt = f"{prompt}\n\n候选按钮如下，请只从这些候选项里选择:\n{option_lines}"
        prompt += "\n\n只输出一行，格式必须为 [ANSWER]按钮原文[/ANSWER]。\n"
        prompt += "如果无法判断，请输出 [ANSWER][UNKNOWN][/ANSWER]。"
        return prompt

    def encode_image(self, image) -> str:
        suffix = Path(getattr(image, "name", "")).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix, "image/png")
        data = base64.b64encode(image.getvalue()).decode("utf-8")
        return f"data:{mime_type};base64,{data}"

    def extract_answer(self, content) -> Optional[str]:
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item) for item in content
            )
        content = (content or "").strip()
        if not content:
            return None
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

        match = re.search(r"\[ANSWER\](.+?)\[/ANSWER\]", content, flags=re.S)
        if match:
            answer = match.group(1).strip()
        else:
            answer = content

        answer = answer.strip().strip("`").strip()
        if answer.upper() == "[UNKNOWN]":
            return None
        return answer

    def match_button(self, answer: str, options: List[str]) -> Optional[str]:
        normalized = " ".join(answer.split())
        digit_match = re.search(r"\d+", normalized)
        if digit_match and digit_match.group(0) in options:
            return digit_match.group(0)
        for option in options:
            if normalized == option:
                return option
        for option in options:
            if option in normalized:
                return option

        matched = process.extractOne(normalized, options)
        if not matched:
            return None

        button, score = matched
        if score < self.llm_button_match_threshold:
            self.log.debug(f"图像模型答案匹配按钮分数过低: {score}/100.")
            return None
        return button

    async def on_button_answer(self, answer: BotCallbackAnswer):
        if not isinstance(answer, BotCallbackAnswer):
            self.log.warning("签到失败: 签到按钮指向 URL, 不受支持.")
            return await self.fail()

        text = (answer.message or "").strip()
        if not text:
            return

        if any(ignore in text for ignore in to_iterable(self.bot_text_ignore_answer)):
            return

        if self.should_process_callback_text(text):
            await self.on_text(Message(id=0, text=text), text)
        else:
            self.log.debug(f"忽略按钮点击回调文本: {text}")

    async def on_captcha_button_answer(self, answer: BotCallbackAnswer):
        if not isinstance(answer, BotCallbackAnswer):
            return

        text = (answer.message or "").strip()
        if not text:
            return

        if self.should_process_callback_text(text):
            await self.on_text(Message(id=0, text=text), text)
        else:
            self.log.debug(f"忽略验证码按钮回调文本: {text}")

    def should_process_callback_text(self, text: str) -> bool:
        keyword_groups = [
            to_iterable(self.bot_account_fail_keywords),
            to_iterable(self.bot_too_many_tries_fail_keywords),
            to_iterable(self.bot_checked_keywords),
            to_iterable(self.bot_fail_keywords),
            to_iterable(self.bot_success_keywords),
        ]
        default_groups = [
            (
                "拉黑",
                "黑名单",
                "冻结",
                "未找到用户",
                "无资格",
                "退出群",
                "退群",
                "加群",
                "加入群聊",
                "请先关注",
                "请先加入",
                "請先加入",
                "未注册",
                "先注册",
                "不存在",
                "不在群组中",
                "你有号吗",
            ),
            ("已尝试", "过多"),
            ("只能", "已经", "过了", "签过", "明日再来", "重复签到", "已签到", "今日已签到"),
            ("失败", "错误", "超时"),
            ("成功", "通过", "完成", "获得"),
        ]
        for custom, default in zip(keyword_groups, default_groups):
            for keyword in custom or default:
                if keyword and keyword in text:
                    return True
        return False


def use(**kw):
    return type("TemplatedClass", (TemplateAICheckin,), kw)
