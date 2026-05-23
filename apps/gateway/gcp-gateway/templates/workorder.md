# 工单 {{workorder_id}}

## 目标
- 项目：`{{project_id}}` / {{project_name}}
- Owner route（归属端路由）：`{{owner_route}}`
- 项目根：`{{project_root}}`
- 创建时间：{{created_at}}

## 当前目标
{{current_goal}}

## 活跃事项
{{active_items}}

## 任务
{{task}}

## 验收口径
- 只执行本工单批准的范围。
- 不直接手写 `workbench.json`、`workbench.events.jsonl` 或 `workbench.history.jsonl`。
- 状态变更和历史摘要由 Faryo 状态机在主控验收时生成。
- 如发现新事项，在 Receipt（回执）里提出建议，不要绕过状态机写入项目真值。

## Receipt（回执）
- Status: pending
- Summary:
- Verification:
- State/event request:
- Remaining blockers:
