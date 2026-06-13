from ._templ_ai import TemplateAICheckin


class MooncakeAICheckin(TemplateAICheckin):
    name = "月饼 AI"
    bot_username = "Moonkkbot"
    bot_checked_keywords = ["今日已签到"]
    llm_prompt = (
        "你在帮助月饼站签到。图片中会出现一个数字验证码，"
        "下方按钮里包含 0 到 9 以及其他功能按钮。"
        "请只选择验证码对应的那个数字按钮，不要选择返回或其他功能键。"
    )
