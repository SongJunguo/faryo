# Faryo Codex TUI Control Clarity Plan

更新时间：2026-08-20
状态：完成并通过隔离浏览器验证

## 问题

Owner 在 Codex 菜单/确认提示出现时显示 `↑`、`↓`、`Enter`，但没有说明它们控制的是 Codex
TUI。用户容易把箭头理解为网页滚动，把 Enter 理解为无条件批准。

## 决策

保留三枚原始按键作为同一 tmux TUI 的通用后备控制，不解析终端文字并伪造独立的
Allow/Deny 操作。终端菜单内容、当前高亮项和不同 Codex 版本会变化；伪造语义按钮可能让
网页动作与桌面所见状态分叉。

显示改为：

```text
Codex menu  [↑ Previous] [↓ Next] [Enter Choose]
```

- 仅在现有 confirm/menu detection 触发时自动展开；
- `tui-controls-visible` 与附件的 `auto-expanded` 独立：仅附件不会带出 TUI 按钮；
- 每个按钮带完整 `title`/`aria-label`；
- Enter 文案明确是选择当前 Codex TUI option，不声称批准；
- 点击 Enter 后立即乐观收起；若 TUI 仍等待选择，下一次 capture 才重新弹出；Up/Down
  保持显示以便连续移动；
- 仍调用既有 `/api/up`、`/api/down`、`/api/approve` 兼容端点，不改变按键协议。

## 验收

- 390x844 与 1440x900 不产生横向页面溢出；
- 普通对话时控件隐藏，真实 TUI prompt 时三枚控件和作用域标签可见；
- Enter 的可见文案、aria 和实际发送键一致；
- 点击 Live/宠物停止控制的语义不改变，tmux geometry 不改变。

## 证据

- Owner HTML 显示 `Codex menu / ↑ Previous / ↓ Next / Enter Choose`，三枚按钮均有与发送键
  一致的 title/aria；API 路径保持兼容。
- 390x844 与 1440x900 匿名浏览器矩阵都验证：普通状态隐藏，`Press enter to confirm or esc
  to go back` fixture 自动展开，Enter 文案与 aria 正确、点击后立即隐藏，页面无横向溢出。
- 剪贴板图片上传期间状态栏会展开显示附件，但 `Codex menu` 保持隐藏；这与真正 TUI prompt
  的可见性已经分别由浏览器断言。
- 两个尺寸都继续通过 20 条发送、剪贴板图片、网络/后台/504 恢复与失败草稿保留；测试前后
  tmux geometry 不变，所有临时 session 清理。
