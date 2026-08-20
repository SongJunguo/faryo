# Faryo Plans

本目录统一管理 Faryo 的实施计划、阶段路线图和完成证据。普通产品说明、安全说明和
交互文档继续保留在 `docs/`；只有带执行阶段、验收条件和进度记录的文档放在这里。

## Active

当前没有活动计划。

## Completed or maintenance mode

- [`v1.4-backend-modernization-and-modularization-plan.md`](v1.4-backend-modernization-and-modularization-plan.md)：
  保留 Python/Conda 和既有安全/可靠性边界，完成 Owner/Gateway/前端职责拆分、唯一
  Starlette/Uvicorn Gateway、35 附件与量化 keyed-list Preact 采用，并发布 source-only v1.4.0；
  完整试点评估位于 [`../preact-pilot-evaluation.md`](../preact-pilot-evaluation.md)。
- [`v1.3-maintainability-and-product-capabilities-plan.md`](v1.3-maintainability-and-product-capabilities-plan.md)：
  用 Playwright/Ruff 与选择性前端库降低维护成本，拆分 Gateway portal，并实施 capability、
  脱敏 diagnostics、只读 diff review 和 body-free attention；pending queue 仅走正式协议。
- [`codebase-architecture-and-mobile-immersive-plan.md`](codebase-architecture-and-mobile-immersive-plan.md)：
  审计代码/依赖/同类项目，实施 Edge 文档滚动、可退出 Fullscreen 与 PWA 补强，并形成
  渐进重构路线。
- [`session-history-archive-plan.md`](session-history-archive-plan.md)：通过 Codex App Server
  正式 RPC 为 Session History 增加可恢复 Archive/Unarchive，不暴露硬删除。
- [`retire-project-orchestration-plan.md`](retire-project-orchestration-plan.md)：退役零配置、零数据
  且含义不清的 `/projects` 编排页面与不可达后端，让 `/` 成为唯一主页。
- [`source-only-ci-release-plan.md`](source-only-ci-release-plan.md)：source-only CI、Python/Node
  运行时发现和已发布的 `v1.2.0` 发布链。
- [`control-audit-session-state-plan.md`](control-audit-session-state-plan.md)：不记录正文的控制
  审计、明确会话状态和准确的 TUI Enter 文案。
- [`tui-control-clarity-plan.md`](tui-control-clarity-plan.md)：方向键和 Enter 明确标为同一
  Codex TUI 的 Previous/Next/Choose 后备控制，并按需自动显示。
- [`live-tmux-reading-copy-plan.md`](live-tmux-reading-copy-plan.md)：当前轮次 180 行 Live 尾部、
  稳定 DOM/滚动/文字选择和显式复制。
- [`chat-raw-mode-switch-plan.md`](chat-raw-mode-switch-plan.md)：隔离 Chat/Raw capture cache，
  修复 Raw 切回 Chat 后仍显示终端原始内容的回归。
- [`clipboard-image-paste-plan.md`](clipboard-image-paste-plan.md)：Owner composer 直接粘贴
  剪贴板图片并复用现有压缩、预览、上传和可靠发送链路。
- [`session-history-search-plan.md`](session-history-search-plan.md)：数百条 Session History 的
  隐私安全服务端元数据搜索与过滤。
- [`directory-picker-redesign-plan.md`](directory-picker-redesign-plan.md)：Start Codex 目录选择器
  使用折叠面包屑、即时搜索、分组目录和固定主操作。
- [`copy-fidelity-plan.md`](copy-fidelity-plan.md)：回答按钮、跨块选择与单公式复制使用
  内存中的原始 Markdown/TeX，并提供安全 HTML。
- [`codex-command-completion-plan.md`](codex-command-completion-plan.md)：从当前 Codex CLI
  的真实命令面板建立 46 项、版本可审计的网页命令提示，并同步 `/rename` 标题。
- [`start-codex-runtime-plan.md`](start-codex-runtime-plan.md)：Gateway `Start Codex`
  的真实就绪、`faryoN` 命名和安全图形目录选择。
- [`full-history-navigation-plan.md`](full-history-navigation-plan.md)：单会话完整 turn 索引、
  游标分页、旧历史懒加载和全问题导航。
- [`codebase-cleanup-plan.md`](codebase-cleanup-plan.md)：收敛为 Ubuntu/Linux + Codex
  单一生产路径，删除不可达资源、旧兼容层和未验证打包链。
- [`codex-reliability-hardening-plan.md`](codex-reliability-hardening-plan.md)：Codex 长会话、
  可靠发送、安全流式认证、历史分页和内部引用展示加固。
- [`deepseek-inspired-ui-plan.md`](deepseek-inspired-ui-plan.md)：DeepSeek Harness 启发的
  Workbench v2 与 Markdown/TeX 重构计划。
- [`personal-fork-roadmap.md`](personal-fork-roadmap.md)：个人 fork 的部署、认证、实时性、
  Gateway 和公网路径总路线图。

## 管理规则

1. 每个活动计划必须写明范围、非目标、阶段、验收标准、验证证据和当前状态。
2. 计划中的真实账号、域名、Token、Cookie、会话正文和本机私有路径不得进入公开仓库。
3. 完成阶段后立即更新证据；不以“代码已写”代替测试、部署和真实浏览器验证。
4. 不修改 Codex tmux/TUI 尺寸；涉及公网身份策略时保留操作者已经确认的选择。
5. 完成的计划保留在本目录并改为维护状态，避免计划散落到仓库其他位置。
