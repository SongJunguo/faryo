# Faryo Live tmux Reading and Copy Plan

更新时间：2026-08-20
状态：完成并通过隔离浏览器验证

## 问题基线

`Live from tmux` 只保留 60 行，并且每遇到新的 `Running` 行就从该命令重新截断，所以稍早的
同一轮 `Explored`、`Edited` 和命令证据会很快消失。Compact Chat 每次刷新还会删除并重建
整个 Live `<details>/<pre>`；用户正在选择文字时，selection anchor 随旧 Text node 被移除，
浏览器会把选择跳到页面其他位置。

## 目标

1. 保留更长的当前用户轮次终端尾部，同时继续限制网络和 DOM 体积。
2. 展开后的可视窗口更高，并继续保留手动滚动位置和 follow-latest 语义。
3. Live DOM 在普通 Chat reconcile 中保持同一节点。
4. 用户在 Live 中选择文字期间暂停内容替换；选择结束后一次性应用最新版本。
5. 提供显式复制按钮，不必依赖容易受实时更新影响的拖选。
6. Raw→Chat 仍自动收起 Live；用户随后手动展开时上述状态继续有效。

## 实现方案

- 服务端 tail 从 60 行提高到 180 行，以最新 user prompt 为当前轮次起点，再应用硬上限；
- Stable Blocks 保留带 `data-faryo-transient="live"` 的节点，不把它当作历史消息删除；
- 浏览器复用同一 `<details>/<pre>`，只更新 `textContent`；
- selection 非折叠且锚点/焦点位于 Live 时，只保存内存中的 latest pending text，并显示
  `Updates paused`；selection 清空后 flush；
- Agent 结束时若仍在选择，延迟移除 Live，避免 selection 被破坏；
- copy 按钮只复制当前可见 `pre.textContent`，不包含隐藏 pending 版本。

## 隐私与资源边界

- pending 文本只存在页面内存，不写 localStorage/sessionStorage、日志或公开 fixture；
- 仍只传当前轮次最多 180 行，不把完整 tmux history 暴露给浏览器；
- Account 元数据继续脱敏；Owner/Gateway 认证和 CSP 不变；
- DOM 稳定化不得改变 tmux geometry 或 Codex TUI。

## 验收标准

- 服务端单元测试证明尾部硬上限 180 行且保留当前轮次较早活动；
- Live 更新后 `<pre>` 节点 identity 不变，手动 scrollTop 误差不超过 2 px；
- selection 期间 revision 不变、选择文本不变、pending 标志出现；取消选择后 latest revision
  一次性应用；
- 显式 Copy 得到当前可见 Live 文本；
- 390x844 与 1440x900 无横向溢出，已有 Chat/Raw、发送和问题导航不回归。

## 实施与证据

- `CODEX_LIVE_TAIL_LINES` 从 60 提高为 180；不再在每个 `Running` 行清空较早的本轮证据，
  仍以最新 user prompt 和 180 行硬上限限制数据量。
- Stable Blocks 明确保留 `data-faryo-transient="live"`；普通 Chat reconcile 不再删除 Live
  `<details>/<pre>`。
- Live 使用 `textContent` 安全更新并递增 revision。selection 位于 Live 时只替换内存中的
  pending latest，标签显示 `Updates paused`；selection 清除后 flush。Agent 结束也延迟删除。
- 可视高度提高到桌面 `min(60vh,560px)`、移动端 `min(56dvh,480px)`，并增加只复制当前可见
  `pre.textContent` 的按钮。
- 新增连续输出的匿名 Codex/rollout/tmux 隔离 fixture。390x844 实测初始 51 行、1440x900
  达到 180 行；两者都通过 same-node、scrollTop 误差不超过 2 px、selection 保持、pending
  flush 和 copy 精确一致。
- fixture 前后 tmux geometry 不变，临时 Owner、session、SQLite、rollout 和上传目录全部清理。
