# Faryo Session History Archive and Restore Plan

更新时间：2026-08-20
目标版本：v1.2.1
状态：完成并部署

## 问题与决策

Session History 已能搜索和查看 Current/Archived，但没有归档或恢复入口。普通硬删除不进入
本计划：删除 thread 及其派生 descendants，恢复成本高，不适合作为常规历史整理操作。

实现必须使用 Codex App Server 正式 thread lifecycle RPC，不直接修改 `state_5.sqlite`、
`session_index.jsonl` 或 rollout 文件。官方协议定义：

- `thread/archive`：移动 rollout 到 archived sessions，并处理派生线程；
- `thread/unarchive`：恢复 archived rollout；
- `thread/delete`：硬删除 thread 与派生线程，本版本不暴露。

本机 Codex 0.148.0 已用不存在的匿名 thread id 验证三种 method 均被识别，而非返回
`method not found`。

## API 方案

Owner：

- `POST /api/agent-session/archive`
- `POST /api/agent-session/unarchive`
- payload 仅含规范化 `agent_session_id`；
- 活跃 tmux/thread 必须返回 `409`，不能在另一个进程持有 thread 时归档；
- 请求前读取 metadata 判断目标当前状态；已经处于目标状态时返回 idempotent success；
- 调用现有长驻 App Server JSONL client，传播受控错误，不回显 rollout 路径；
- 成功后重新读取 metadata 验证 archived 状态，有限等待后仍不一致则返回明确错误。

Gateway：

- `POST /api/session-history/archive`
- `POST /api/session-history/unarchive`
- 要求 inner login、CSRF、允许 route；
- 仅代理当前用户 workspace scope 内 Owner 可见的 thread；
- 控制审计增加 `archive` / `unarchive`，target 继续只存 HMAC alias。

## 前端方案

- Resumable 卡片增加 `Archive` 次级按钮；
- Archived 卡片增加 `Restore` 按钮；
- Archive 使用可撤销但仍明确的确认 sheet；Restore 可直接执行；
- 操作期间卡片禁用，成功后保持现有 q/period/archive/page 条件刷新；
- Active/Starting/Running/Waiting/Desktop/Exited 卡片不显示 Archive；
- 不增加 Delete 按钮、隐藏快捷键或未说明的 destructive API。

## 测试矩阵

1. Owner archive/unarchive success、already-target-state idempotency、unknown id；
2. active thread、descendant ownership/app-server conflict、timeout、进程重启恢复；
3. Gateway login/route/CSRF、Owner error mapping和 body-free audit；
4. Current→Archived→Current 的总数、分页、搜索和 URL filter 保持；
5. 390x844/1440x900 按钮、确认、忙状态、无横向溢出；
6. 匿名临时 Codex home/rollout 的真实 archive/unarchive 往返，原文件内容 hash 不变；
7. 发送、Start/Resume/Close、公式、复制、Live selection 和 tmux geometry 回归。

## 验收标准

- 已知历史会话可从 Current 归档，并在 Archived 中恢复；
- 全程只通过 App Server RPC 改变 thread lifecycle；
- 归档失败不会半写 SQLite 或由 Faryo 移动 rollout；
- 没有硬删除入口；
- 公开 fixture 不包含真实 thread id、标题、路径或正文。

## 完成证据

- Owner 已实现归档/恢复、active/superseded 冲突、workspace scope、幂等和有限状态确认；
- Gateway 已实现登录、route、CSRF、Owner 状态映射及 body-free HMAC 审计；
- 82 个 Owner 与 62 个 Gateway Python 测试及 canonical source check 全部通过；
- 匿名临时 Codex home 通过真实 App Server 完成 Current→Archived→Current 往返，rollout
  SHA-256 不变，操作者真实 Codex home 未被读取或改写；
- 390x844 Chrome 与 1440x900 Edge 验证卡片资格、Archive 确认、Restore、无 Delete、历史
  分页/搜索与无横向溢出；
- 部署后 Owner/Gateway 健康，现有 Codex tmux 窗口尺寸保持不变。
