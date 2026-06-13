from typing import List, Literal, Optional, Union
from loguru import logger
from pydantic import BaseModel, ValidationError

from . import Messager

__ignore__ = True


class TemplateAMessagerConfig(BaseModel):
    name: str = None
    chat_name: Optional[Union[str, int]] = None  # 发送群聊名称
    messages: List[str] = None  # 使用的语料, 与 message_lists 二选一
    message_lists: Union[str, List[str]] = (
        []
    )  # 使用的语料列表, 例如 ["some-wl@v1.yaml * 1000"], 放置在 basedir 中, 且 @v1.yaml 尾缀是必须的
    min_interval: Optional[int] = None  # 发送最小间隔 (秒)
    max_interval: Optional[int] = None  # 发送最大间隔 (秒)
    at: Optional[List[str]] = None  # 时间区间, 例如 ["5:00AM", "9:00PM"]
    possibility: Optional[float] = None  # 发送概率, 例如 1.00
    only: Optional[Literal["weekday", "weekend"]] = None  # 仅在周末/周中发送
    max_count_recent_5: int = 1
    max_count_recent_10: int = 1

    # Backward compatibility
    interval: Optional[int] = None


class TemplateAMessager(Messager):
    additional_auth = ["prime"]

    async def init(self):
        try:
            self.t_config = TemplateAMessagerConfig.model_validate(self.config)
        except ValidationError as e:
            self.log.warning(f"初始化失败: 水群器自定义模板 A 的配置错误:\n{e}")
            return False
        self.name = self.t_config.name or "自定义"
        self.chat_name = self.t_config.chat_name
        self.default_messages = self.t_config.message_lists
        self.at = self.t_config.at
        self.possibility = self.t_config.possibility
        self.only = self.t_config.only
        self.max_count_recent_5 = self.t_config.max_count_recent_5
        self.max_count_recent_10 = self.t_config.max_count_recent_10
        # messages / min_interval / max_interval 由 config 读取
        if not self.chat_name:
            self.log.warning(f"初始化失败: 没有定义任何目标群组, 请参考教程进行配置.")
            return False
        self.log = logger.bind(scheme="telemessager", name=self.name, username=self.me.full_name)
        return True


def use(**kw):
    return type("TemplatedClass", (TemplateAMessager,), kw)
