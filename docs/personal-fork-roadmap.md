# Faryo 个人 Fork 完善路线图

更新时间：2026-08-12

当前分支：`katex-feature`

个人仓库：`origin`（`SongJunguo/faryo`）

原作者仓库：`upstream`（`Snailflyer/faryo`）

## 总目标

把个人 Faryo fork 完善为可长期使用的本机 Codex Web 客户端：优先实现结构化消息实时同步与可靠输入提交，再完成安全 Markdown、离线 KaTeX、本机自启、端到端测试、文档和个人 GitHub 推送，同时保持 tmux TUI 可用且不修改原作者 upstream。

对应工作 Goal：`019ff509-e143-7473-af25-0fbc57de0d20`。

## 当前架构边界

当前网页有两条不同的数据路径，排查时不能混为一谈：

1. **结构化显示路径**：Owner 通过独立的 `codex app-server` 读取线程历史，网页用 `/api/events` 和结构化快照显示消息、Markdown 与公式。
2. **交互输入与 Raw 路径**：正在运行的 Codex TUI 仍位于 tmux 中；`/api/send` 目前通过 tmux 粘贴文本并发送按键，Raw 视图也来自 tmux pane。

因此，“从 JSON 读取显示”并不等于“输入也由 App Server 提交”。在完成架构验证前，不允许网页 App Server 与独立 Codex TUI 同时成为同一线程的 turn writer，以免出现并发写入、重复消息或会话状态损坏。

## 当前基线

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| Owner Token 认证 | 已完成并提交 | 页面读取和 `/api/send` 都已携带认证；旧 Token 页面仍会返回 401 |
| 结构化公式来源 | 已完成并提交 | 公式不再依赖有损的 tmux 屏幕文本 |
| tmux 桌面换行 | 已完成并提交 | Owner 不再把 Codex 窗口强制扩到 500 列 |
| 公式版式 | 已完成并提交 | 分段函数、范数和块公式已经过 Chrome/Edge 验证 |
| KaTeX 本地化 | 已实现，待提交 | 本地 JS、CSS、字体和许可证已通过离线浏览器检查 |
| 安全 Markdown | 已实现，待提交 | markdown-it、公式保护、XSS 用例和浏览器回归通过 |
| 网页输入可靠提交 | **P0 已完成，待提交** | 消息 ID 幂等、粘贴/Enter 确认、失败草稿保留和 TUI 草稿冲突保护均通过 |
| 结构化消息实时更新 | **P0 已完成，待提交** | 最终内容用结构化数据；运行中显示脱敏 tmux live 尾部，结束后自动收敛 |
| 本机开机自启 | 已完成 | user timer 已启用，`Linger=yes`；停止 Owner 后的自动恢复测试通过 |
| 手机/Gateway/隧道 | 后续阶段 | 不属于本机 P0 修复；本机稳定后再配置 |

已推送的个人 fork 提交：

- `fd2b4d6`：KaTeX 渲染与 Owner 认证修复。
- `23d78bf`：从 Codex 结构化 transcript 渲染公式。
- `56a4109`：保持真实 tmux 客户端宽度。

## 阶段 1：可靠输入提交（P0，已完成）

### 工作项

- 在一次性测试会话中稳定复现“本次文本留在 TUI、下一次才提交”的竞态，不向用户现有会话注入测试内容。
- 逐层记录浏览器请求、Owner `/api/send`、tmux paste、Enter 以及 Codex 接受输入的时序。
- 把 `/api/send` 从“按键已发送”改为“提交结果已确认”的语义。
- 浏览器只有收到确认后才能清空草稿；超时或失败时保留/恢复原文本，并显示可重试错误。
- 防止双击、重复请求和旧请求晚到造成重复 turn。

### 验收标准

- 连续发送至少 20 条短消息、中文消息、多行消息和含公式消息，全部一次提交。
- 任意失败都不得静默丢失浏览器草稿。
- 请求成功时，Codex TUI 输入框已清空或已出现明确的 turn 开始证据。
- 不改变已有桌面 tmux 客户端的宽度、换行与快捷键行为。

## 阶段 2：结构化消息实时同步（P0，已完成）

### 工作项

- 测量消息在 Codex TUI、线程持久化、`thread/read`、Owner SSE 和网页 DOM 五个位置的时间差。
- 修正 App Server 初始化流程，并验证独立 App Server 能否观察由独立 TUI 写入的增量。
- 检查当前 0.6 秒缓存、请求串行化和 SSE 去重是否吞掉或延迟更新。
- 根据实测在以下方案中选择最小可靠实现：
  - 监听结构化会话文件变化并立即刷新；或
  - 让单一 App Server 成为会话 owner，并由其事件通知驱动网页。
- 增加 SSE 断线重连、页面隐藏后恢复和线程切换测试。

### 验收标准

- 用户消息、流式回复和 turn 完成状态无需刷新即可出现。
- 正常本机条件下，从新内容产生到网页可见不超过 2 秒。
- 页面断网/休眠后恢复能够自动补齐，不重复、不漏消息。
- 结构化视图与 Raw/tmux 对同一 turn 的最终内容一致。

## 阶段 3：Markdown 与离线公式资源（已完成）

### 工作项

- 完成本地 `markdown-it` 与 KaTeX 资源打包，运行时不依赖 CDN。
- 支持标题、列表、强调、引用、代码、表格、链接、图片以及块级/行内公式。
- 禁止原始 HTML 执行，拦截危险协议，并继续复用 Owner 的本地文件访问边界。
- 保持代码块中的 `$`、`\\(` 等内容为原文，不误渲染成公式。

### 验收标准

- Node 单元测试、Owner smoke、Gateway 测试、Chrome 与 Edge 浏览器测试全部通过。
- 断网/DNS 不可用时 Markdown、KaTeX CSS、JS 和字体仍从 `127.0.0.1` 加载。
- XSS 用例、危险链接、路径越界和未认证请求均被拒绝。

## 阶段 4：部署、回归与发布

### 工作项

- 安装并验证用户级 systemd 自启/保活单元，不依赖登录后手动启动。
- 验证 Token 文件权限、日志脱敏、重启恢复和端口占用处理。
- 执行完整功能矩阵：认证、发送、实时更新、Markdown、公式、文件链接、Raw、tmux 宽度。
- 将每类改动拆成可审查提交，推送到个人 `origin`；不向 `upstream` 推送。
- 更新 README，写清启动、停止、故障恢复和已知限制。

## 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| 单元 | Markdown/数学保护、协议校验、输入确认状态机 |
| 服务 | Token、`/api/send`、SSE、结构化快照、文件访问 |
| tmux | paste/Enter 时序、附着客户端宽度、长行换行 |
| 浏览器 | Chrome、Edge、断线重连、草稿保留、公式和 Markdown |
| 部署 | 重启、自启、日志、权限、本地离线资源 |

## 执行规则

- 每次只推进一个可验证的小阶段；测试通过后再提交。
- 所有 Python 命令先执行 `conda env list`，并使用项目的 `faryo` 环境。
- 不在真实用户会话中注入诊断消息；交互测试使用一次性 tmux/Codex 会话。
- 不打印或提交 Owner Token。
- 不把“HTTP 200”当成消息已提交；必须有 Codex 接受 turn 的确认。
- 遇到架构分叉先记录证据和取舍，再决定是否迁移输入所有权。

## 下一步

完成最终 diff/敏感信息审查，重新运行全量测试，将改动提交并只推送到个人 `origin/katex-feature`。手机 Gateway/隧道继续保留为后续独立阶段。

## 2026-08-12 验证记录

- 输入成功路径：真实 Owner HTTP 返回 `delivery=accepted`；同一 `clientMessageId` 第二次请求返回 `duplicate=true`，没有重复粘贴。
- 输入失败路径：人为保留 TUI 草稿后，Chrome 收到冲突错误，输入框和 `sessionStorage` 草稿均未被清空。
- 实时路径：独立 App Server 可在约 0.28 秒看到 TUI 新用户消息，但进行中的 shell turn 直到完成前没有结构化 item；因此采用“结构化最终内容 + 临时脱敏 tmux live 尾部”。Chrome 验证 live 面板自动出现并在完成后自动消失。
- Markdown/公式：Node 单元测试、11 个 Owner Python 测试、13 个 Gateway 测试、包发布检查和 Owner smoke 全部通过。
- 浏览器：Chrome 与 Edge 本地资源测试通过；`\\begin{cases}`、`\\|d(t)\\|\\le M` 和至少两行矩阵结构的精确 KaTeX 检查通过。
- 部署：`faryo-owner-keepalive.timer` 已启用；主动停止 Owner 后，keepalive 成功用 `/home/sjg/miniconda3/envs/faryo/bin/python` 恢复服务。
