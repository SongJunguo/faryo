# Faryo Plans

本目录统一管理 Faryo 的实施计划、阶段路线图和完成证据。普通产品说明、安全说明和
交互文档继续保留在 `docs/`；只有带执行阶段、验收条件和进度记录的文档放在这里。

## Active

当前没有未完成的实施计划。新工作先在本节登记，再开始大范围修改。

## Completed or maintenance mode

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
