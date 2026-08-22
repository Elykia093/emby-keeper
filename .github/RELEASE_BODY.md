## What's Changed

1. AI 识别支持多后端回退，`[checkiner.ai]` 新增 `fallbacks` 与 `base_url`，主后端失败时自动切换备用模型或 OpenAI 兼容服务商。
2. 内容审核拦截单独识别并提示，日志中可与超时、网络错误区分，并显示当前后端序号与模型名。
3. 视觉识别提示词移除固定开场白，支持通过 `[checkiner.ai].llm_prompt` 自定义。

**Full Changelog**: https://github.com/Elykia093/emby-keeper/compare/v7.6.4...v7.6.5
