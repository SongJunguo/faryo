# Faryo Control Audit and Session State Plan

更新时间：2026-08-20
状态：完成并部署验证

## 问题基线

Faryo 是可以控制 Codex 和工作站的远程界面，但当前日志主要记录 HTTP method/path。发生
Close、Interrupt、Enter 或 Start 时，无法从隐私安全证据判断操作者、目标和结果。

同时，tmux 顶层命令可能显示 `bash`，真正的 Codex 是其 descendant；managed 会话又可能
经历启动、运行、等待输入、Codex 退出回到 shell 等阶段。主页目前主要用 Running/Waiting，
不足以表达这些状态。

## 目标

1. 建立不记录消息正文的控制操作审计。
2. 为 managed/desktop 会话提供明确、可测试的生命周期状态。
3. 让未知关闭、重复启动、失败清理和权限确认具有可追踪证据。
4. 保留用户要求的 Cloudflare/内层登录策略，不新增 MFA 或 broad bypass。

## 审计记录边界

私有 mode-600 JSONL，默认保留 7 天或 5000 条，字段仅包括：

- UTC 时间、request id；
- Gateway 用户名、route；
- `start/resume/close/send/interrupt/enter/up/down/file-inject` 动作；
- 使用 Gateway secret HMAC 后截断的 session/thread 标识；
- HTTP/result 状态、耗时和幂等命中状态。

严禁记录：

- prompt、回答、附件正文、标题、cwd；
- Token、Cookie、CSRF、Cloudflare credential；
- 原始 session/thread id、命令参数、浏览器密码或 IP 全量历史。

审计 API 只对当前已认证用户返回其可见 route 的最近记录；公开测试只使用匿名值。

## 会话状态机

| 状态 | 证据 |
|---|---|
| `starting` | Faryo managed 标记存在，Codex 启动尚未完成且在就绪期限内 |
| `running` | 真实 Codex descendant 存在，TUI 当前不接受输入 |
| `waiting` | 真实 Codex descendant 存在，TUI 已准备输入 |
| `exited` | managed tmux 仍在，但 Codex descendant 已退出 |
| `desktop` | 非 Faryo managed、真实 Codex descendant 存在 |
| `resumable` | 无活动 tmux、Codex metadata 可恢复 |

状态判断以进程树、rollout/thread 映射和显式 managed option 为准，不能仅看
`pane_current_command`。`exited` 会话短暂显示并允许安全 Close，超过既有 TTL 后精确清理。

## 前端方案

- Active 卡片显示 Starting/Running/Waiting/Exited/Desktop；
- `Confirm` 重命名为 `Enter`，说明“确认当前 TUI 高亮项”，不再暗示自动批准；
- 设置菜单增加 `Security activity`，显示最近动作、结果和相对时间，不显示消息内容；
- 提供“退出当前网页登录”和“撤销全部内层 Faryo 会话”的清晰区别；后者需要再次确认，
  不关闭 Codex/tmux。

## 测试矩阵

1. start success/timeout/lost response/idempotent retry；
2. Codex descendant under bash wrapper、waiting/running transition、exit shell；
3. desktop session 不获得 managed Close；
4. 每种控制操作成功/拒绝/超时的审计记录；
5. 日志轮转、权限 600、损坏尾行、并发写；
6. 审计 API 用户/route scope、CSRF 和缓存控制；
7. 全仓库扫描确认正文、Token、原始 session id 不进入记录；
8. 手机/桌面状态展示、Enter 文案和确认行为；
9. 发送幂等、历史、公式、复制、目录与 tmux 几何回归。

## 验收标准

- 任一控制动作可回答“何时、哪个 Faryo 用户、对哪个匿名目标、做了什么、结果如何”；
- 不能从审计文件还原会话 id、路径或对话内容；
- UI 状态与真实进程树一致；
- `Enter` 不再被文案描述为无条件 approve；
- 审计功能失败不能阻塞正常控制请求。

## 实施与证据

- Gateway 在 control response 边界审计 start/resume/close/send/interrupt/enter/up/down/
  file-inject/revoke-sessions；CSRF 拒绝也记录，但在读取请求体前完成，因此目标与正文为空。
- 私有 `control-audit.jsonl` 使用 Gateway Cookie secret 对 target 做 HMAC 并截断为
  `t_` + 16 hex；文件 mode 600，保留最近 7 天且不超过 5000 条，损坏行跳过。
- 审计写入为 best-effort 单次 append；I/O 异常被隔离，不改变 control response。API 只返回
  当前登录用户和其允许 route，且不回传内部 username 字段。
- 设置菜单新增 Security activity、Sign out this device 和二次确认的 Revoke signed-in devices；
  revoke 只提升内层 auth epoch，不停止 Codex/tmux。
- Owner 启动时写 `@faryo_starting_at`，真实 descendant 出现后清除。process tree、managed
  option 与 TUI prompt 共同产生 Starting/Running/Waiting/Exited/Desktop；非活动 metadata 为
  Resumable/Archived。
- managed Codex 退出回到 shell 时仍显示 Exited 并允许 Close；desktop session 不获得 Close。
  `Confirm` 已改为带明确 aria/title 的 `Enter`。
- 匿名测试覆盖全部 proxy control 动作、direct start/resume/file-inject、成功/403/502、幂等
  字段、用户/route scope、损坏尾行、3-row 缩小轮转、I/O 故障和 revoke auth epoch。
- 生产只用缺少 CSRF 的匿名 interrupt 验证安全拒绝：Owner/tmux 未收到请求，审计 mode 600、
  denied=403，body marker 不在文件。随后真实 Start Codex→ready→Close 通过，start/close target
  仅为 HMAC，测试 session 精确清理，原有 session 集合与 geometry 完全一致。
- 生产 Gateway 当前匿名计数证据为 1 Running、1 Waiting、10 Resumable；390x844 与 1440x900
  浏览器均通过显式 lifecycle dataset、Security activity 隐私文案、历史搜索和分页。
