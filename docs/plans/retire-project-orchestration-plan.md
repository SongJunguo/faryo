# Faryo Project Orchestration Retirement Plan

更新时间：2026-08-20
目标版本：v1.2.1
状态：完成并部署

## 问题基线

`/projects` 是早期高级项目编排面板，不是会话主页。它管理 project definition、stage、
decision/action/watch、workorder、Owner downlink 和 receipt verification；当前主品牌入口却跳到
该页面，用户无法从界面理解它与 Codex Session History 的关系。

本机只读核验：

- Gateway project-workbench projection：0 行；
- downlink package：0 个；
- 私有 Gateway env 中 project/workbench 配置键：0 个。

因此它不属于当前 Ubuntu/Linux + Codex 单用户生产路径。运行时私有目录即使为空也不删除，
只退役仓库代码与公开路由。

## 目标

1. `/` 成为唯一 Gateway 主页面；品牌链接回 `/`，不再把用户送入未知功能。
2. 移除 `/projects` HTML/CSS/JS 与 manifest/route allowlist。
3. 删除未被主工作台、文件 handoff、Owner session、认证或审计使用的 project orchestration
   后端、模板、profile 和测试。
4. 保留通用 Files to session / bridge package；不能把“handoff”误当作 project downlink 一并删掉。
5. 私有 `~/.faryo`、Codex rollout、tmux 和用户项目目录保持只读/原样。

## 删除边界

候选范围必须通过引用图逐项证明不可达：

- Gateway `/api/project-workbench*`、project stage/direction/submit/import；
- `/api/faryo/start|dispatch|workorder/verify` 中仅服务 Project controller 的路径；
- `project-workbench.jsonl` / downlink runtime plumbing；
- Owner project definition/workbench/workorder/downlink endpoints；
- `projects.html`、`projects.css`、`projects.js`、Project profile/template 和专用测试。

明确保留：

- Gateway `/`、Active/History/Start Codex；
- bridge package 上传与 Files to session；
- Owner structured history、send、attachment、directory、session lifecycle；
- security activity、Cloudflare/inner auth、MCP handoff 工具；
- shared appearance 与通用 state helper，除非全仓库引用证明专用于 Projects。

## 实施顺序

1. 建立符号/路由/静态资源/测试引用清单；
2. 先改品牌入口并删除浏览器 route/assets；
3. 删除 Gateway orchestration server slices；
4. 删除 Owner orchestration slices和无引用 helper；
5. 收紧 source assertions，任何 Projects 路由/静态资源重新出现即失败；
6. 运行完整测试、真实 Gateway 浏览器与部署回归。

## 验收标准

- `/`、会话页、文件 handoff 全部正常；`/projects` 返回 404，不重定向到含糊页面；
- 仓库不再包含 Projects 静态资源或 production Project endpoints；
- 当前私有项目/下行目录没有被删除或改写；
- 代码/测试净减少且 canonical source check 全绿；
- 手机/桌面主页品牌行为明确、无旧缓存资源、tmux geometry 不变。

## 完成证据

- `/` 已是唯一主页，品牌返回 `/`；认证后的 `/projects` 明确返回 404；
- Projects 静态页面、专用 controller/workorder/downlink 后端、模板和无引用 state helper
  已删除，变更净减少约 4,000 行；
- 通用 Files-to-session、bridge package、Start/Resume/Close、历史和 Owner session 路径保留；
- Owner 初始化器会删除旧 project-workbench 配置键，并在需要时迁移目录根；生产迁移保持
  Token、显式目录根和 mode-600 权限不变；
- 82 个 Owner 与 62 个 Gateway Python 测试、canonical source check、390x844 Chrome、
  1440x900 Edge 和真实部署健康检查全部通过；
- 未删除或改写私有 runtime 目录、Codex rollout、用户项目或现有 agent tmux，会话尺寸不变。
