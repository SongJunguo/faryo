# Faryo Copy Fidelity Plan

更新时间：2026-08-19
状态：已完成并部署；进入浏览器兼容性维护

## 已报告问题

从 Compact Chat 复制内容时格式混乱，公式尤其明显。需要分别审计：

1. 回答块 `⧉` 按钮复制；
2. 桌面鼠标框选后 `Ctrl/Cmd+C`；
3. 手机长按选择复制；
4. 单个行内/展示公式的复制。

KaTeX DOM 同时包含视觉 HTML、MathML 辅助层和原始 TeX annotation。直接让浏览器从
渲染 DOM 生成纯文本，可能重复上下标、拆散矩阵/cases、混入辅助文本或丢失 Markdown
边界。这与公式是否正确显示是两条独立链路。

## 目标

1. `⧉` 始终复制该回答的原始 Markdown/TeX 源码，不从视觉 DOM 反推。
2. 框选多个消息时，`text/plain` 使用对应原始块并保持段落、列表、表格、代码围栏与
   TeX 定界符；不复制按钮、问题轨道、Live tmux 或内部引用标记。
3. 框选单个公式时复制规范的原始 TeX，而不是 KaTeX 视觉字符或 MathML 双份文本。
4. 在支持的浏览器中同时提供安全 `text/html`，粘贴到富文本编辑器仍有合理结构；不
   支持时可靠回退纯文本。
5. 手机和桌面使用同一来源映射，不依赖浏览器私有 DOM 序列化行为。

## 数据与实现原则

- 渲染时为每个稳定 block 保留内存中的原始 source 映射；不得写入 localStorage、
  sessionStorage、DOM 明文属性或日志；
- 公式节点通过 KaTeX 的 `application/x-tex` annotation 或渲染前 AST source 映射回
  原始 TeX；优先使用 AST source，annotation 只作受控回退；
- `copy` 事件只在选择范围完全位于 Compact Chat 输出区时接管；输入框、Raw、代码块
  自带复制和系统级复制行为不得被破坏；
- 部分跨 block 选择要按 DOM Range 边界裁剪首尾文本，不能粗暴复制整个对话；
- `<oai-mem-citation>` 等内部标记继续以卡片显示，但不得进入复制正文；
- Clipboard API 失败时保留浏览器默认复制，不清空用户剪贴板。

## 测试矩阵

1. 行内 `$...$`、展示 `\[...\]`、cases、aligned、矩阵、上下标和根式；
2. GFM 表格含公式、列表含公式、代码围栏内的 TeX 字面量；
3. 一个回答按钮复制、单公式选择、半段文字、跨两个回答和 user+assistant 混合选择；
4. Copy 按钮、代码 Copy、手工选择三条路径互不干扰；
5. 内部 memory card、受保护文件链接、图片、Live tmux 和问题导航不污染剪贴板；
6. 390x844 Chrome/Android Edge 行为与 1440x900 Edge/Chrome；
7. 剪贴板权限拒绝、ClipboardItem 不可用和 `execCommand` 不可用的降级；
8. Markdown/KaTeX/Shiki、全历史、发送和 composer 回归。

## 验收标准

- 匿名 fixture 的复制结果与预期 Markdown/TeX 字符串逐字节一致；
- 真实公式回答只做哈希/长度/结构检查，不把正文写入测试输出；
- 手工复制后粘贴到纯文本与 Markdown 编辑器均保持可读公式源码；
- 浏览器 DOM 中不新增完整回答 source 属性，不泄露 Token、路径或内部注解；
- 完成后记录根因、各浏览器能力、测试数量和提交，并移入 Completed。

## 根因与实现

- 回答按钮原本已优先读取内存 source，但鼠标框选/手机长按仍使用浏览器对 KaTeX
  视觉 HTML + MathML 的默认序列化，因此出现上下标拆散、矩阵重复和公式定界符丢失；
- 新的 `copy-fidelity.js` 为当前渲染轮次建立 WeakMap：稳定消息 block 映射到去除内部
  annotation 的原始 Markdown，KaTeX 节点映射到 Markdown AST position 对应的原始 TeX；
- 原始回答不写入 DOM attribute、storage 或日志；DOM 仅保留 `ready/bound` 布尔健康标记；
- 完整 block 和跨完整消息复制原始 source；部分首尾 block 通过 Range 裁剪并把相交公式
  扩展为完整 TeX，再用受限 Markdown serializer 恢复段落、标题、列表、表格和代码围栏；
- 单公式选择直接复制原始 `\(...\)`、`\[...]`、`$...$` 或 `$$...$$`；KaTeX
  annotation 只在 AST 映射缺失时回退；
- `text/html` 删除全部 data/style 属性、本地链接目标、图片资源、KaTeX 双层 DOM、内部
  memory 卡、Live tmux 和操作按钮；公式以安全 `<code>` TeX 表示；
- 选择位于嵌套代码块、Raw 视图、输入框或 Compact Chat 外时不接管系统复制；没有
  `clipboardData` 时不调用 `preventDefault()`，保留浏览器默认路径；
- Compact Chat 的根元素历史上是 `<pre id="output">`；代码块判断现已明确排除这个外层
  容器，只把其内部真实 `pre/code` 当作代码选择，避免误判所有对话选区。

## 完成证据

- 匿名 fixture 对回答按钮 source、完整回答、user+assistant+Live 跨区、部分文字到公式、
  单公式、表格、列表、代码围栏和 memory card 做逐字节比较，全部通过；
- 代码块选区与缺少剪贴板对象的事件保持浏览器默认行为；安全 HTML 包含表格结构且不含
  source attribute、内部 metadata、Live 内容、Token 或本地路径；
- 真实公式回答只返回非零字节数、64 位 SHA-256 形状和布尔结构检查；正文不进入测试
  输出或公开文档；单公式 annotation 只出现一次；
- Ubuntu Google Chrome 与 Microsoft Edge 均通过 1440x900、390x844 两种视口；回答
  按钮、框选与公式三条路径一致；
- Owner 68 项、Gateway 50 项 Python 测试以及全部 JavaScript 测试通过；Markdown、KaTeX、
  全历史、命令面板、发送与 Start Codex 联合回归通过；
- 部署测试前后所有既有 Codex tmux 几何不变，且没有残留测试会话。
