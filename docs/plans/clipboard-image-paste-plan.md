# Faryo Clipboard Image Paste Plan

更新时间：2026-08-20
状态：完成并通过隔离浏览器验证

## 问题基线

Owner 对话页已经支持通过 Attach 按钮或拖放上传图片，并具有压缩、进度、缩略图、移除、
最多 35 个附件和可靠发送逻辑；但在桌面截图工具或手机剪贴板复制图片后，仍必须另存或重新
打开文件选择器。

## 目标

1. 光标位于 composer 时，直接粘贴剪贴板图片即可进入现有附件队列。
2. 立即显示缩略图与上传进度，发送前可移除，失败时保留文字草稿。
3. 图片与同一次 clipboard event 中的纯文本可以同时保留。
4. 复用现有压缩、上传、附件路径和发送幂等链路，不建立第二套协议。
5. 桌面 Chrome/Edge 与浏览器实际暴露 image `File` 的移动端均可使用；不支持图片 paste
   的浏览器继续使用 Attach 作为明确回退。

## 安全与隐私边界

- 只响应用户在 `promptInput` 上触发的 `paste` event；不调用
  `navigator.clipboard.read()`，不在后台读取剪贴板。
- 只拦截 clipboard 中的 `image/*` file item；纯文本 paste 保持浏览器原生行为。
- 同时包含图片和纯文本时，手工插入 `text/plain`，不读取 HTML clipboard 内容。
- Blob URL 只用于本页缩略图并在移除/成功发送时撤销；图片、文件名和本机上传路径不写入
  localStorage/sessionStorage 或公开日志。
- 继续沿用 Owner token/CSRF、25 MiB 单文件服务端上限、35 个附件上限、随机私有落盘名和既有
  workspace/inbox 边界。

## 实现方案

1. 新增独立的 clipboard item 解析与 textarea 文本插入 helper，便于无 DOM 单元测试。
2. `promptInput` paste handler 从 `clipboardData.items` 获取 image file；旧浏览器回退到
   `clipboardData.files`。
3. 命中图片时 `preventDefault()`，先保留同 event 的纯文本，再调用现有
   `uploadAttachments()`。
4. 预览、压缩、取消、错误、发送成功清理全部复用现有实现。
5. Quick tools 的 Attach 说明增加 `or paste an image`，让能力可发现但不占用 composer
   常驻空间。

## 测试矩阵

1. 纯文本 paste 不被拦截；image-only paste 被拦截并上传。
2. image + text 同时粘贴时，文本按 selection range 插入且图片只入队一次。
3. `clipboardData.items`/`files` fallback、非图片 file、空 clipboard。
4. 多图和已有附件共同遵守 35 个上限，压缩/上传并发不超过 4，不产生重复上传。
5. PNG fixture 缩略图、进度、移除、压缩/上传失败和发送后清理。
6. 真实浏览器经 clipboard event 上传匿名 PNG，并由 tmux receiver 确认只提交一次。
7. 390x844 与 1440x900 composer 几何、文字 paste、拖放、Attach、发送恢复和 tmux 尺寸
   不回归。

## 验收标准

- 复制截图后在输入框粘贴即可看到一个可移除的图片缩略图；
- 附带文字和图片的消息只发送一次，504/重试仍遵循现有幂等契约；
- 未发生图片 paste 时，浏览器原生文字粘贴行为完全不变；
- 页面不申请持久 clipboard 权限，也不读取非用户触发的剪贴板内容；
- 公开 fixture 不包含真实图片、会话文字、Token、域名或本机路径。

## 实施与证据

- 新增无依赖 `clipboard-images.js`：优先解析 clipboard items，回退 files，只接受
  `image/*`，并以纯函数保留 selection range 中的 `text/plain`。
- composer 仅在 paste event 确实含图片时调用 `preventDefault()`；纯文字 event 的浏览器
  默认行为未被阻止，也没有使用 `navigator.clipboard.read()`。
- 图片继续复用现有最多 35 个、四路压缩/上传、进度、可横向滚动缩略图、取消、CSRF 上传、
  失败保留和发送后 Blob URL 清理链路；Gateway 已代理新增静态 helper。
- Node 单元测试覆盖 items/files fallback、非图片排除、异常 clipboard、文本读取和 selection
  替换。
- 隔离 Owner + 临时 tmux receiver 在 390x844 与 1440x900 Chrome 均通过：匿名 PNG paste
  被正确拦截、同 event caption 保留、缩略图只有 1 个、上传成功、提交只发生 1 次、无需
  reload，随后网络/后台/504 恢复仍无重复。
- 两次浏览器矩阵均确认测试前后 tmux geometry 不变，并清理临时 session 与上传目录。
- 本机 Owner/Gateway 已加载新增 helper；经认证 Gateway 代理返回 HTTP 200，真实现有会话在
  390x844 Chrome 只读加载检查确认 `faryoClipboardPaste=ready`。真实 Codex 会话未发送测试
  内容，全部 agent tmux window geometry 保持不变。
