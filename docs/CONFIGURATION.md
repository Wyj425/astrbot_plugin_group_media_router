# 配置说明

只在插件自己的配置页填写。不要把真实配置提交到 GitHub。

| 设置 | 默认值 | 说明 |
|---|---|---|
| `platform_id` | "" | QQ机器人ID 首次安装请填写当前 AstrBot 中实际配置的接入或提供商 ID。 |
| `default_rules` | null | 默认回复规则（未单独设置的群沿用） |
| `group_rules` | [] | 各群单独回复规则 |
| `allowed_groups` | [] | 高级：插件生效群号或会话ID（空列表为全部群） |
| `stale_chat_groups` | [] | 高级：跳过排队过久的概率闲聊的群号 |
| `stale_chat_seconds` | 30 | 高级：概率闲聊最大排队时间（秒） |
