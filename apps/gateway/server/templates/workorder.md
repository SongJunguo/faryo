# 工单 {{workorder_id}}

## 目标
- 项目：`{{project_id}}` / {{project_name}}
- Owner route（归属端路由）：`{{owner_route}}`
- 项目根：`{{project_root}}`
- 创建时间：{{created_at}}
- 派发前真值 hash（哈希）：`{{workbench_hash}}`

## 本轮绑定 item（事项）
{{active_items}}

## 执行方式
- 先读取 `00-system/workbench.json`，按上方 ID 定位本轮绑定 item（事项）。
- 先理解 `decision`（裁决项）和 `watch`（说明项）作为本轮上下文，再执行 `action`（执行项）。
- 若绑定 item 缺失，或本轮没有 `action`（执行项），停止并在 Receipt（回执）写阻塞。

## 任务
{{task}}

## 验收口径
- 只执行本工单批准的范围。
- 不直接手写 `workbench.json`、`workbench.events.jsonl` 或 `workbench.history.jsonl`。
- Receipt（回执）提交后由主控做业务验收，通过时再由 Faryo 状态机生成历史摘要。
- 如发现新事项，在 Receipt（回执）里提出建议，不要绕过状态机写入项目真值。

## Receipt（回执）
- Status: pending
- Execution process:
- Summary:
- Verification:
- Files/evidence:
- New items or blockers:
