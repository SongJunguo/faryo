# Faryo 个人 Fork 完善路线图

更新时间：2026-08-15

当前分支：`feature/deepseek-inspired-ui`

个人仓库：`origin`（`SongJunguo/faryo`）

原作者仓库：`upstream`（`Snailflyer/faryo`）

## 总目标

把个人 Faryo fork 完善为可长期使用的本机 Codex Web 客户端：优先实现结构化消息实时同步与可靠输入提交，再完成安全 Markdown、离线 KaTeX、本机自启、端到端测试、文档和个人 GitHub 推送，同时保持 tmux TUI 可用且不修改原作者 upstream。

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
| tmux 桌面换行 | 已完成并提交 | Owner 默认宽度为 0，不执行尺寸调整；Codex 窗口始终由真实 tmux 客户端决定 |
| 公式版式 | 已完成并提交 | 分段函数、范数和块公式已经过 Chrome/Edge 验证 |
| KaTeX 本地化 | 已完成 | KaTeX 0.18.4 已打入 AST bundle；CSS、字体和许可证继续离线提供 |
| 安全 Markdown | AST v2 已实现，最终验收中 | 单一 micromark/mdast/GFM/math 管线、Shiki 按需高亮和稳定块 DOM 对账已接入；旧实现已移除 |
| 网页输入可靠提交 | **P0 已完成并推送** | 消息 ID 幂等、粘贴/Enter 确认、失败草稿保留和 TUI 草稿冲突保护均通过 |
| 结构化消息实时更新 | **P0 已完成并推送** | 最终内容用结构化数据；运行中显示脱敏 tmux live 尾部，结束后自动收敛 |
| 本机开机自启 | 已完成 | user timer 已启用，`Linger=yes`；停止 Owner 后的自动恢复测试通过 |
| 手机/Gateway/隧道 | 已部署 | Gateway 与 Owner 均仅监听回环地址；公网主路径位于精确身份限制的 Cloudflare Access 外层，采用 24 小时会话且关闭独立 MFA；仓库不保存允许身份或域名 |

已推送的个人 fork 提交：

- `fd2b4d6`：KaTeX 渲染与 Owner 认证修复。
- `23d78bf`：从 Codex 结构化 transcript 渲染公式。
- `56a4109`：保持真实 tmux 客户端宽度。
- `1892a1d`：可靠输入、实时更新、安全 Markdown 与离线 KaTeX。
- `76d5097`：加固结构化 Codex 公式来源与通用公式回归样例。
- `89eb9aa`：以 AST/KaTeX/Shiki 和稳定块对账替换旧 Markdown/数学双实现。
- `d8681d7`：完成手机优先工作台、桌面阅读主轴和发布浏览器检查。
- `2a47821`：补齐研究常用语言的按需 Shiki 浏览器高亮。
- `50a118e`：增加匿名精确投递、附件、恢复与 TUI 尺寸浏览器矩阵。
- `e50d899`：普通聊天收起低频终端按键，真实审批提示按需展开。

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

## 阶段 3：Markdown、离线公式与增量稳定块（AST v2 已实现，发布回归中）

### 渲染技术选择

CommonMark 本身不定义 TeX 数学语法。旧实现用 Markdown 解析前保护公式、
解析后再扫描 DOM，复杂表格、受损定界符和流式半成品会穿过多层启发式。
当前功能分支已经改为与 DeepSeek Harness 同类的单一 AST 管线：
`micromark -> mdast -> GFM/math nodes -> safe HTML -> KaTeX`。流式阶段
只启用 GFM，最终结构化消息再启用 math；表格、代码、正文与公式因此由
语法节点而不是正则猜测区分。生产端仍只加载仓库内预构建 bundle，不需要
Node 运行时或 CDN。

### 工作项

- 锁定 micromark/mdast/GFM/math/KaTeX 依赖、构建命令和完整许可证，运行时不依赖 CDN。
- 支持标题、列表、强调、引用、代码、表格、链接、图片以及块级/行内公式。
- 禁止原始 HTML 执行，拦截危险协议，并继续复用 Owner 的本地文件访问边界。
- 最终验收后删除旧解析器、auto-render 和终端公式猜测链；回滚只依赖 Git 标签和备份分支。
- 保持代码块中的 `$`、`\\(` 等内容为原文，不误渲染成公式。
- 使用 Shiki JavaScript regex engine，高频语言预热、研究/系统语言按需加载，失败时
  保持纯文本代码回退。
- 只重建变化的 Compact Chat 块；稳定历史节点原样复用，内存渲染缓存最多 256 项。

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

完成最终差异和隐私审计，提交本轮可靠交互覆盖并推送个人 `origin`；随后进行用户实际
长对话观感验收。由于网页能够控制终端 Agent，公网长期使用必须保留受限 Cloudflare
Access（或仅可信设备可达的私网 VPN）作为外层身份策略，不能由 Tunnel 或 Faryo
单密码替代。

## 2026-08-12 验证记录

- 输入成功路径：真实 Owner HTTP 返回 `delivery=accepted`；同一 `clientMessageId` 第二次请求返回 `duplicate=true`，没有重复粘贴。
- 输入失败路径：人为保留 TUI 草稿后，Chrome 收到冲突错误，输入框和 `sessionStorage` 草稿均未被清空。
- 实时路径：独立 App Server 可在约 0.28 秒看到 TUI 新用户消息，但进行中的 shell turn 直到完成前没有结构化 item；因此采用“结构化最终内容 + 临时脱敏 tmux live 尾部”。Chrome 验证 live 面板自动出现并在完成后自动消失。
- Markdown/公式：Node 单元测试、14 个 Owner Python 测试、26 个 Gateway 测试、包发布检查和 Owner smoke 全部通过。

## 2026-08-15 AST v2 验证记录

- AST 源码测试 9/9；稳定块单元测试覆盖 200 块历史追加时复用 200、仅创建 1。
- Owner Python 20/20、Gateway Python 37/37、发布检查和 Owner HTTP/tmux smoke 通过。
- 新增可重复的匿名终端交付矩阵：20 条短文本、中文、多行、Markdown/TeX 都以内容
  SHA-256 ACK 验证一次提交；ACK 总数严格匹配，无截断、无重复、无需刷新。
- 隔离临时 inbox 的真实浏览器附件上传与引用提交通过；断网和页面后台期间的输出在恢复
  后自动补齐，缺失会话的失败发送保留输入框与 `sessionStorage` 草稿。
- 匿名手机/桌面富文本截图以真实 AST 公式表格和分段函数完成目检；普通聊天收起低频
  终端按键，真实审批提示自动展开方向键与 Confirm，并纳入可重复浏览器矩阵。
- 同一完整矩阵在已部署 Owner 的 390x844 和 1440x900 视口通过；Owner/Gateway 重启
  前后 4 个既有 Agent tmux 窗口尺寸完全不变。
- Chrome 390x844 深色与 1440x900 浅色匿名夹具通过 GFM、分段公式、五行公式表、
  CJK 粗体、代码隔离、Shiki TypeScript/Python/LaTeX/Lean/MATLAB、本地资源、XSS
  和内部横向滚动检查。
- 匿名网页发送成功/失败草稿、SSE 自动更新、手机/桌面 Live 滚动和既有 tmux 尺寸
  不变均通过；未向真实会话注入测试消息。
- Gateway 重启后六个计划视口均通过登录代理回归；活动/历史分区、10 条分页和页码跳转
  通过；本轮再次以精确 390x844 和 1440x900 DOM 视口验证无横向溢出，Edge 另通过
  390x844 和 1440x900。未登录本地请求与公网 Cloudflare Access 边界均正确拦截。
- 匿名手机/桌面截图只在 `/tmp` 目检并已删除；公开仓库隐私与密钥模式扫描无命中。
- 浏览器：Chrome 与 Edge 本地资源测试通过；分段函数、范数和至少两行矩阵结构的精确 KaTeX 检查通过。
- 部署：`faryo-owner-keepalive.timer` 已启用；主动停止 Owner 后，keepalive 成功使用专用 Conda 环境恢复服务。
- 发布：功能提交 `1892a1d` 已推送到个人 `origin/katex-feature`；原作者 `upstream` 未修改。

### Gateway 与手机公网路径

- Gateway 只加载 `FARYO_GATEWAY_ROUTES` 中启用的路由；单路由部署不再要求为 HP、PC 等禁用路由填写伪 Token。
- Gateway 和 Owner 都仅监听 `127.0.0.1`，Owner Token 只保存在权限为 `600` 的私有运行时配置中，由 Gateway 服务端注入。
- Gateway 用户级 systemd 服务已完成启用、重启与健康检查；登录 Cookie、CSRF、登录限速和浏览器安全头均有回归覆盖。
- 现有命名 Cloudflare Tunnel 在保留原有路由的前提下增加独立 Faryo hostname；公网 TLS、登录、真实结构化 Markdown/KaTeX 和一次性测试会话输入提交均通过。
- 公网验证只使用通用测试文本；仓库中不记录真实域名、Token、密码、会话名、对话内容或本机绝对路径。
- Cloudflare Tunnel 负责连通，不等于 Cloudflare Access。当前公网入口以覆盖完整 hostname 的两个精确邮箱规则限制身份，Access 应用会话为 24 小时，应用级独立 MFA 按低摩擦使用需求关闭；Email One-time PIN、Google 和 GitHub 登录入口均可选且不强制跳转到单一提供商。无 `Everyone`、无 `Bypass`，并保留 Faryo 登录作为内层认证。真实邮箱和域名只存在于私有 Cloudflare 配置中。
- 已增加隐私安全的公网验收脚本：它不接收或打印密码、Cookie、Token 与 hostname；只有确认请求先进入 Access 登录流程才返回通过，直接到达 Faryo 登录或无法判定都不会误报为安全。
- Gateway 代码加固包含：所有浏览器写请求（含 Owner 代理）使用会话绑定 CSRF、登录限速使用可信代理提供的单值客户端地址、`__Host-` 严格 Cookie、nonce CSP 及已有安全响应头。内层登录期限现可由私有 `FARYO_GATEWAY_SESSION_HOURS` 在 `1`–`168` 小时内配置，默认 12 小时；当前个人部署与 Access 一致设为 24 小时。Agent 权限策略仍由操作者决定，Faryo 不强制降低 Codex/Claude 权限。
- Gateway user service 已以私有 24 小时配置重启；真实本地登录响应验证 `Max-Age=86400`，且 `Secure`、`HttpOnly`、`SameSite=Strict` 属性保持不变。该重启未改变任何既有 tmux 窗口尺寸。
- Gateway 首页已拆成两个独立区域：`Active Sessions` 始终显示所有实际运行 Codex/Claude 的 tmux（包括桌面直接启动的会话），`Session History` 排除活动项、独立滚动，并由服务端按 10 条一页提供 Previous/Next 和页码直达。只有 Faryo 管理的会话提供远程关闭，桌面 tmux 仅可打开查看，避免误关。
- 运行会话上限与历史显示数量解耦；单机 TXY 默认允许 8 个存活 Agent TUI，并可通过私有 `FARYO_TXY_MAX_RUNNING` 在 1–32 范围内调整。

### 结构化来源加固

- Owner 服务可通过私有运行时配置 `FARYO_CODEX_BIN` 定位 Codex CLI，避免版本管理器安装目录未进入服务 `PATH` 时静默退回终端屏幕文本。
- 紧凑视图会标记实际 capture source；Codex 结构化历史不可用时显示明确警告，而不再把可能残缺的终端回退误认为完整 Markdown。
- 通用回归样例覆盖行内/行间公式、分段函数、指示函数、平方根表达式和终端换行恢复；测试数据不包含真实对话、Token、域名或本机绝对路径。
- `Live from tmux` 内层滚动已改为终端语义：首次显示定位最新内容，停留底部时随输出更新，用户手动上翻后刷新保持阅读位置；纯函数回归与真实公网 Chrome 动态刷新检查均通过。
