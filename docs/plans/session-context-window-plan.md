# Session Context Window Plan

状态：实施中

## 目标

让用户在新建 Codex 会话和恢复历史会话时，为该次启动选择独立的上下文窗口。界面提供
`Default`、`272K`、`1M` 预设以及以 `K` 为单位的整数输入；默认值继续继承工作站上的
Codex 配置，不修改 `~/.codex/config.toml`。

## 设计

1. 上下文选择器与现有工作目录选择器放在同一张启动面板中，目录导航时保留已输入的值。
2. 普通历史卡片点击继续快速恢复并继承默认配置；`Resume options` 同时提供目录和上下文
   选择，避免每次恢复都增加一个阻塞步骤。
3. Gateway 和 Owner 分别验证 `context_window_k`，只允许当前支持范围内的整数，Owner 再把
   它转换成一次性 Codex CLI `-c` 参数。
4. 自定义窗口同时设置 `model_context_window` 和 90% 的
   `model_auto_compact_token_limit`，避免较大的窗口仍被全局较小阈值提前压缩，也避免较小
   窗口沿用过大的压缩阈值。
5. 选择只作用于新启动的 tmux/Codex 进程；恢复不会删除历史，Codex 仍负责在活动窗口达到
   阈值时压缩上下文。状态栏继续显示 Codex 实际报告的可用窗口。

## 安全与兼容边界

- 不接受任意 CLI 参数、TOML 文本或 shell 片段，只接受有界整数。
- 不修改现有 tmux 几何、可靠发送、认证、目录签名、Markdown/TeX 或实时流路径。
- 不把账号、域名、Token、本机私有路径、会话标题或正文写入公开测试和文档。
- 默认路径不携带覆盖值，因此升级前的行为保持不变。

## 启动环境隔离补强

实施中发现，长期运行的 tmux server 可能保留创建它的旧 Faryo 服务环境，使后来启动的
Codex 误用旧版 `PYTHONPATH`，并让不属于 agent 的服务内部变量跨越进程边界。本版本同时：

- 从 systemd unit 删除运行时已不需要的源码 `PYTHONPATH`；
- Owner 启动和每次 managed launch 前清除 tmux 全局环境中的 Faryo/Gateway 内部变量，
  只在确认属于 Faryo 安装根时移除对应 `PYTHONPATH` 分量；
- tmux client、Codex CLI、自动更新和共享 App Server 使用脱敏子进程环境；
- 保留 HOME、PATH、代理、Codex 配置和用户自己的其他 Python 路径。

## 验收标准

- 新建和 `Resume options` 都能提交自定义 `272K`，并提供 `1M` 预设。
- 目录上下移动或切换隐藏目录后，上下文选择不丢失。
- Gateway 与 Owner 都拒绝越界或非整数输入；默认值不产生 CLI 覆盖。
- Owner 为自定义值生成正确的窗口与自动压缩参数，启动重试仍保持幂等。
- 新启动的 managed Codex 和未来重建的 tmux server 不包含 Faryo 私有运行变量或旧安装
  Python 路径；既有 tmux/Codex 进程不被强制关闭。
- Python、JavaScript、浏览器、source gate 和真实部署回归通过；普通刷新即可取得新资产。

## 证据

待实现和验证后补充。
