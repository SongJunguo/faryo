# Faryo Codebase Architecture and Mobile Immersive Plan

更新时间：2026-08-20
目标版本：v1.2.2
状态：完成并部署

## 目标

本计划同时回答并完成三件事：

1. 用可复核指标判断 Faryo 当前代码和文件结构是否沉重、哪里值得重构；
2. 对照 Happy、Happier、Harness Remote、Tether、Codex Remote 等公开项目，形成适合
   Faryo 的功能优先级，而不是机械复制大而全架构；
3. 为手机长对话同时提供普通 Edge/Chromium 原生工具栏随文档滚动收起、可由用户手势
   进入并明确退出的 Fullscreen，以及安装后的 PWA standalone 路径。

## 公开与安全边界

- 计划、测试 fixture 和报告不写真实域名、邮箱、Token、Cookie、会话 ID、对话正文或
  私有绝对路径；
- 不自动进入全屏，不使用滚动 1 px 等不可靠技巧欺骗浏览器界面；
- Fullscreen API 只能由明确用户手势触发，退出按钮始终可发现，系统返回手势和 Esc 仍有效；
- 不改变 Cloudflare/inner login、Owner token 注入、可靠发送或 Codex 权限策略；
- 不改变 tmux/Codex TUI 窗口尺寸；
- 不因追求体积删除离线 KaTeX、Shiki 语言块、字体或它们的许可证。

## 当前基线

截至 v1.2.1：

- 237 个 Git 跟踪文件，约 5.6 MB；Git pack 约 2.5 MB；
- 生产与测试 Python/JavaScript/CSS/HTML/shell 合计约 23,241 行；
- 38 个测试或浏览器 smoke 文件；
- Owner `server.py` 4052 行、202 个顶层函数，HTTP Handler 531 行；
- Gateway `server.py` 2038 行，Gateway Handler 964 行；
- Owner `app.js` 2554 行、`style.css` 1401 行；
- 约 3.25 MB 是本地 Markdown/KaTeX/Shiki vendor 资产，是断网公式和代码高亮能力的
  有意成本；本机 `__pycache__` 不受 Git 跟踪，不属于发布包袱。

初步判断：仓库总量较轻、顶层边界清楚，风险主要是少数单文件内部耦合和 Gateway 把
HTML/CSS/JavaScript 嵌入 Python，并不是文件过多。适合渐进抽取高变化、可独立测试的
模块，不适合为了“现代化”立即改写成大型前端框架或原生 App。

## 依赖策略：轻量不等于零依赖

- 成熟库能显著减少解析、安全、可访问性或跨浏览器风险时，应优先评估库而不是重复实现；
- 依赖必须有清晰许可证、锁定版本、生成来源、离线本地资产和 CI 验证，不通过 CDN 运行；
- 引入前记录增加的压缩体积、构建链、维护活跃度和退出成本；
- screenfull 适合一般 Fullscreen API 封装，但其当前 ESM 集成会给本项目新增构建层，且仍不
  支持 iPhone；本次保留独立、Node 可测的薄适配层，后续一旦建立统一前端 bundle 再复评；
- Floating UI 适合替换 Gateway 当前手写的弹层碰撞定位，列为近期候选；
- Playwright 和 Ruff 是优先级更高的开发依赖候选：前者收敛重复 CDP 浏览器脚本，后者在
  Python 单文件拆分前提供快速约束；它们不进入生产运行时；
- 只读 diff 和 attention/push 真正进入实施时，优先评估 diff2html 与 Python Web Push
  成熟实现，不手写 unified-diff parser、VAPID 或 payload encryption；
- Preact 或 Lit 只在 Gateway 静态资源先从 Python 抽离、共享状态接口稳定后再做小范围试点，
  不以框架迁移本身作为目标。

## 工作流 A：结构审计与有限重构

1. 建立 tracked size、语言行数、最长函数、类/Handler 规模和测试覆盖基线；
2. 检查生产引用、重复状态机、嵌入静态资源、vendor  provenance 和生成缓存；
3. 将新沉浸式行为实现为独立、无依赖、Node 可测的浏览器模块，避免继续扩大 `app.js`；
4. 只删除引用图证明不可达的文件；不进行跨后端大迁移；
5. 输出短期/中期/不建议三档重构路线与明确触发条件。

## 工作流 B：同类项目对照

只使用项目仓库、许可证和官方文档。至少比较：

- Happy：原生 iOS/Android/Web、设备切换、推送、端到端加密；
- Happier：attention inbox、可编辑 pending queue、智能通知、诊断恢复、session fork/handoff；
- Harness Remote：PWA/Capacitor、backend capability discovery、手机/桌面自适应、完成提示；
- Tether：attach-first supervision、通知渠道、显式 human-in-the-loop gate；
- Codex Remote：App Server bridge、QR pairing、照片、reasoning/permission 控制和通知。

输出必须区分：现在值得做、需要协议重构后再做、不符合 Faryo 单用户/同一 tmux 定位。

## 工作流 C：手机沉浸显示

### 浏览器约束

普通标签页的地址栏/底栏由浏览器控制，页面不能任意强制隐藏。Faryo v1.2.1 把根页面
锁定，长对话滚动发生在内部 `main`，Edge 因而看不到顶层文档滚动。

### 产品方案

1. 仅对经 Gateway 打开的窄屏普通浏览器启用文档根滚动；直接 Owner、桌面和 standalone
   PWA 保留原会话滚动器；
2. 通过独立 scroll-surface adapter 统一 scrollTop/scrollHeight、事件、历史锚点和问题导航，
   不使用滚动 1 px 或伪造浏览器状态；
3. 保持 manifest `display: standalone`：安装后的 Faryo 从图标启动，不显示普通地址栏；
4. Owner 多页面也引用根 manifest，使会话页具备同一 PWA 身份；
5. 会话标题栏提供 `Enter full screen`，只在真实点击/触摸后调用 `requestFullscreen()`；
6. 使用 `fullscreenchange` 同步状态；展开标题栏显示 `Exit`，折叠标题栏显示独立退出按钮；
7. 系统手势、浏览器 Back 或 Esc 退出后立即恢复按钮状态；
8. 不支持或拒绝 Fullscreen API 时给出可读提示，并引导使用主页的 Install app；
9. 不永久记住全屏，避免刷新或新会话在没有用户意图时自动进入。

## 验证矩阵

1. 纯 Node 状态机：supported/unsupported、enter/exit、Promise rejection、external exit；
2. Chrome/Edge 浏览器：真实点击产生 fullscreen 请求，按钮/ARIA/焦点/退出路径正确；
3. 390x844 Gateway 普通标签页：document scrolling element 确实高于视口，可信滚轮/触摸
   改变 `window.scrollY`，内部 `main.scrollTop` 保持 0，固定 composer 可见；
4. 390x844 与 1440x900：无横向溢出，安全区、composer、问题导航和面板不重叠；
5. standalone media mode、manifest link、PWA scope 和 service worker 路径；
6. Markdown/TeX、复制、Live、Chat/Raw、可靠发送、Session History 与 Start Codex 回归；
7. 部署前后 Owner/Gateway 健康，所有现有 tmux 几何逐项不变；
8. canonical source check、隐私扫描、公开 README/交互/架构说明同步。

## 验收标准

- 给出数据化的“包袱是否重、是否值得重构”结论和阶段路线，不只做主观评价；
- 给出同类项目功能矩阵及 Faryo 的采用/延后/拒绝理由；
- Android/Chromium 普通标签页能产生真实文档滚动，使浏览器具备原生自动收栏条件；
- Android/Chromium 路径能一键进入沉浸全屏并一键退出，失败时不破坏页面；
- 安装 PWA 仍是更稳定的无地址栏路径，普通浏览器使用不受影响；
- 新功能采用独立模块和独立测试，不继续把全部逻辑塞进 `app.js`；
- 所有生产与浏览器回归通过后才更新状态、推送与发布。

## 当前验证记录

- Fullscreen header/Details/折叠标题栏退出已通过 390x844 Chrome、Edge 和 1440x900 Edge；
- 手机截图确认“四角展开”仍显示，说明当时处于普通标签页而非 Fullscreen；旧内部滚动没有
  触发 Edge 工具栏收起；
- 首次真实 Gateway 文档滚动验收在 app-ready 过早取样时失败；等待结构化历史稳定后，根文档
  已有真实滚动距离；
- 第二次验收发现 `body overflow-x:hidden` 会按 CSS 规则把纵向 overflow 计算成 auto，创建
  错误的 sticky scroll container；改为 body `overflow:visible`，横向裁剪只由根元素负责；
- 修复后 390x844 Edge/Chrome 可信触摸使 `window.scrollY` 改变，`main.scrollTop=0`，sticky
  header、问题导航和 fixed composer 正常；Edge 连续重复两次通过，tmux geometry 不变；
- 浏览器工具栏最终是否收起仍由 Edge 决定；文档根滚动这一必要条件已满足，保留真机刷新复验。

## 完成证据

- 公开架构报告记录 237 个跟踪文件、约 5.6 MB、核心单文件热点、依赖准则、同类项目矩阵
  和 P0/P1/P2 路线；
- 根 `AGENTS.md` 已按操作者要求收敛为三条“轻量不等于零依赖”原则；
- 新增独立 immersive-mode 与 scroll-surface 模块及纯 Node 测试，没有新增 CDN、框架或
  native runtime；
- canonical source check 通过：82 个 Owner、63 个 Gateway Python 测试以及全部维护中的
  JavaScript/source contracts；
- 390x844 Edge/Chrome 与 1440x900 Edge 通过 Fullscreen header/Details/折叠退出；真实
  Gateway 可信触摸根滚动、问题导航、固定 composer 和无横向溢出通过；
- 40 轮历史、KaTeX/Shiki、受保护资源、Raw→Chat、20 条可靠发送、剪贴板图片、离线恢复、
  跨会话隔离和 Live 选择/复制矩阵全部通过；
- Owner/Gateway 已部署 v1.2.2 且健康，所有现有 agent tmux 窗口保持 145x44。
