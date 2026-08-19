# Faryo Full-History Navigation Plan

更新时间：2026-08-19
状态：已完成

## 问题基线

Owner 当前只向浏览器提供受行数与字符预算约束的最近完整 turn。默认策略至少保留最近
12 个 turn，右侧问题导航再从当前 DOM 的 `.compact-block.user` 元素生成标记。因此：

- 导航标记数量只等于当前渲染窗口，不等于会话完整用户提问数；
- 旧问题可能仍存在于 Codex rollout，却无法从网页查看或跳转；
- 现有真实浏览器测试只验证“至少若干标记”，没有比较完整历史总数。

这不是公式渲染或 tmux 捕获问题，而是结构化历史的数据契约不完整。

## 目标

1. 单会话问题导航能够表示 rollout 中全部可显示用户 turn。
2. 首屏继续只传输最近一页，旧内容按游标向前加载，避免把大型 rollout 整体发送到手机。
3. 点击尚未加载的问题标记时，自动取回包含该问题的页面并跳转。
4. 滚动到历史顶部时可继续加载更早页面，同时保持当前阅读锚点。
5. Codex 工作期间只增量更新尾页；已加载旧页不被重复解析或替换。
6. 线程旋转、文件截断、暂时不可读或请求失败时安全回退到现有最近历史，不丢草稿、不
   影响发送与 Live tmux。

## 非目标

- 不把整个 rollout、工具调用或内部事件发送到浏览器；
- 不修改 Codex/tmux 窗口尺寸；
- 不把 rollout 路径、Token、Cookie、会话正文或真实问题预览写入公开测试和日志；
- 不以简单增大 `CODEX_TRANSCRIPT_MIN_TURNS` 作为最终方案；
- 不改变 Gateway 的 Session History；它管理不同会话，本计划处理单个会话内部的 turn。

## 服务端方案

### 完整 turn 索引

- 按 rollout 文件 identity、已读字节和完整换行边界维护增量索引；
- 只记录可显示 user/assistant message 的 turn 边界、稳定 key、用户预览和必要字节位置；
- 首次冷读逐行扫描但不保留工具事件正文；追加时只读取新增完整 JSONL；
- 文件替换、缩短或 thread 旋转时丢弃旧索引并重建；
- 索引设置路径数量与内存上限，遵循现有 LRU/锁模型。

### 分页契约

新增认证 API，返回：

- 当前结构化 source/revision；
- `totalTurns`、当前页 `start/end`、`hasOlder/hasNewer`；
- 不透明的向前/向后游标；
- 当前页完整 Markdown/TeX turn；
- 全问题轻量索引只包含稳定 key、序号和经过长度限制的用户预览。

所有游标都绑定当前 thread revision；旧游标不得跨 thread 静默读取错误会话。

## 前端方案

- 首次加载最近一页并建立 `turn key -> DOM block` 映射；
- 问题轨道以服务端全问题索引为准，不再只依赖当前 DOM；
- 点击未加载标记时按游标加载对应页，合并到稳定 block 模型后跳转；
- 接近顶部时预取上一页；prepend 前后用锚点元素和高度差保持阅读位置；
- 尾部实时刷新只替换当前尾页，旧页保持 DOM identity、公式状态和内部滚动位置；
- 加载失败显示可重试状态，已有历史与输入草稿保持不变。

## 测试矩阵

1. 40+ 个 user turn 的匿名 rollout，包含长 Markdown、表格、cases、矩阵和代码。
2. 首屏只加载最近页，但导航总数等于完整 user turn 数。
3. 点击最早、中间和最新问题，分别触发懒加载并准确定位。
4. 顶部连续加载多页，滚动锚点不跳动、不重复 block。
5. rollout 追加半条 JSON、补全记录、文件替换和 thread 旋转。
6. 页面刷新、断网恢复、重复请求与过期游标。
7. 390x844 Chrome 与 1440x900 Edge；公式、代码、问题轨道均无页面横向溢出。
8. 现有 20 条发送、双会话隔离、附件、认证、CSP 与重启幂等测试全部继续通过。
9. 私有真实长会话只比较计数与 DOM 结构，不记录问题文本、路径或 thread id。
10. 部署前后所有真实 Codex tmux 尺寸一致。

## 验收标准

- `total user turns == question rail total == eventual loaded user turns`；
- 首屏响应保持有界，旧历史通过分页取得；
- 冷索引和增量追加有明确耗时/内存证据；
- 公开仓库隐私扫描通过；
- Owner/Gateway 部署健康，真实长会话完成首条到末条跳转；
- 完成后在本文件记录 API、提交、性能和浏览器证据，并移入计划索引的 Completed 区。

## 完成证据

- 新增 `codex_history_state` 增量索引和认证
  `GET /api/conversation-history`；索引只保存 message 字节范围、稳定 question key 与
  88 字符预览，游标绑定 rollout revision；
- 首屏契约从依赖行数的“至少 12”收敛为“最多 12 个完整 turn”，短回答也不会一次
  把任意数量 turn 推到手机；
- 前端保持已加载页，实时 capture 只触发受 2.5 秒节流保护的尾页更新；重复首屏请求
  被合并，真实 Gateway 验证一次 latest + 一次 older cursor，无每秒请求风暴；
- 问题轨道以完整索引为准，未加载标记使用虚线状态；顶部加载使用两帧相对锚点校准，
  点击未加载标记会先取回对应页面；
- 新增匿名 40-turn 浏览器矩阵：首屏 12、顶部预取后 24、点击最早问题后继续加载并
  最终达到 `40 total = 40 markers = 40 loaded`，旧页公式由 KaTeX 渲染；
- 真实长会话在手机 Chrome 与桌面 Edge、直接 Owner 与 Gateway `/txy/` 下均达到
  `14 total = 14 markers = 14 loaded`；诊断只输出计数，不输出正文、路径或 thread id；
- 当前机器冷索引 0.0129 秒、同 revision 热索引低于 0.0001 秒、12-turn 页读取
  0.0003 秒，测试进程峰值 RSS 38,744 KiB；
- 主页会话分页与单会话正文分页使用不同函数名，并有防冲突回归；曾出现的列表 0
  回归已恢复为真实 6 个活动会话、458 条历史、每页 10 条；
- 68 个 Owner 与 50 个 Gateway Python 测试、Markdown/KaTeX/Shiki、20 条发送、附件、
  离线恢复、双会话隔离、手机/桌面布局和隐私安全浏览器检查全部通过；
- 刷新定位回归在真实长会话中先把滚动位置置顶再执行浏览器 reload；结构化首页稳定后
  Edge 桌面与 Chrome 手机均回到最底部。随后模拟人工向上滚动并触发 capture refresh，
  阅读位置保持不变；匿名 40-turn 懒加载与顶部锚点测试继续通过；
- 部署期间所有既有 Codex tmux 保持各自原始尺寸，没有调用 `resize-window`。
