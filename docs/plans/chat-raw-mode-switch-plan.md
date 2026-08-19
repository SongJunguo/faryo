# Faryo Chat and Raw Mode Switch Regression Plan

更新时间：2026-08-20
状态：完成并部署验证

## 问题基线

用户在 Owner 会话页从 Chat 切换到 Raw 后能看到终端原始内容，但再次切回 Chat 时，按钮状态
虽然恢复，输出仍可能保留 Raw capture 的代码/终端文本，而不是重新生成 Markdown/TeX 富文本。

当前 `lastCapture` 同时承担 Chat structured/streaming capture 与 Raw HTML capture 缓存。Raw 刷新
会覆盖它；切回 Chat 的同步首帧又立即重放这个 Raw capture，且 Markdown highlighter/history 的
异步回调也可能再次重放同一个错误缓存。即使随后网络刷新通常能够纠正，慢请求、切换竞态或
中断连接都会让错误页面长期停留。

## 目标

1. Chat 与 Raw 使用彼此独立的最近成功 capture，不能跨模式重放。
2. Raw→Chat 的同步首帧立即恢复最近 Chat Markdown/TeX DOM，不依赖下一次网络更新。
3. 首次进入某模式而尚无该模式 cache 时显示明确 loading state，不把另一模式伪装成结果。
4. 保留 Raw 二次点击锁定、Live tmux、历史懒加载、复制、滚动锚点和自动刷新语义。

## 实现方案

- 增加 `lastCompactCapture` 与 `lastFullCapture`；`renderOutput` 按当前模式更新相应 cache。
- mode switch 只重放目标模式 cache；Markdown highlighter 和 conversation-history 回调只能重放
  compact cache。
- session switch 同时清空两个 cache，避免跨会话复用。
- 目标模式无 cache 时渲染无敏感内容的 loading placeholder，再发起目标格式 capture。

## 测试矩阵

1. structured JSONL：Chat formula/Markdown → Raw → Chat，富文本节点和 capture source 恢复；
2. tmux fallback：Chat safe Markdown → Raw HTML → Chat safe Markdown；
3. 快速 Chat/Raw/Chat 与延迟/取消请求不会让旧 Raw response 赢得竞态；
4. Raw 锁定/解锁、Chat SSE 重连、question navigator、copy fidelity 与滚动位置；
5. 390x844、1440x900、真实部署页面和 tmux geometry。

## 验收标准

- 切回 Chat 后不需要手动刷新即可出现 `.compact-block`/`.markdown-body` 和可用 KaTeX；
- Chat DOM 不含 Raw terminal HTML 的残留结构；
- 模式按钮、Details 面板与实际 DOM 状态一致；
- 不改变 Codex/tmux 尺寸，不发送消息，不记录真实对话内容。

## 实施与证据

- 用户补充确认：Raw 会把终端直接铺在对话区并移除独立 Live panel，切回 Chat 后错误状态
  没有恢复。这与共享 `lastCapture` 的代码路径一致。
- 新增 `lastCompactCapture`/`lastFullCapture`；highlighter、history merge 和 mode switch 不再
  重放通用 `lastCapture`，session switch 同时清空两份 cache。
- 目标模式第一次没有 cache 时显示 loading placeholder；不会把 Raw DOM 标成 Chat。
- compact-rules 单元 fixture 证明 Edited/diff 行仍收敛成 Editing files/Diff summary，摘要中不
  含源代码，因此“修改文件没有收起”不是 compact rule 漏判。
- 390x844 structured 40-turn JSONL fixture 通过 Raw→Chat、KaTeX、完整历史和 40 个问题导航；
  tmux fallback fixture 也通过 Raw→Chat、GFM/KaTeX/Shiki 与保护资源检查。
- 本机部署后的真实 Codex structured 页面在 390x844 和 1440x900 Chrome 均通过：切回 Chat
  的同步首帧已有 compact/markdown DOM，稳定后 capture source 仍为 `codex-jsonl`，没有 Raw
  process `<pre>` 残留。
- 部署与测试没有发送消息；全部真实 agent tmux window geometry 保持不变。
