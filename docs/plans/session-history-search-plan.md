# Faryo Session History Search and Filter Plan

更新时间：2026-08-20
状态：排队中；等待 Source-only CI 完成后实施

## 问题基线

当前真实 Gateway 有数百条可恢复会话，主页只提供每页 10 条、Previous/Next 和页码跳转。
用户知道会话标题、项目目录或大致日期时，仍需逐页寻找。

## 目标

1. 服务端按会话元数据搜索，不下载或扫描对话正文。
2. 支持标题、工作目录名称、日期范围和归档状态过滤。
3. Active Sessions 与 Session History 继续分离，搜索结果总数和分页准确。
4. 手机与桌面提供一个清晰搜索框和轻量 filter chips。
5. 搜索条件可进入 URL query 以便刷新/返回，但不写入 storage。

## 数据与隐私边界

允许查询：

- Codex SQLite 的 thread id、初始 title、cwd、created/updated time、archived；
- `session_index.jsonl` 中 Codex 显式 rename 后的 thread name；
- 当前 Gateway route/workspace scope。

禁止查询或记录：

- user/assistant message、rollout 正文、工具参数；
- Token、Cookie、完整本机绝对路径日志；
- 浏览器搜索历史或跨用户结果。

## API 方案

扩展既有 `/api/workbench` 和 Owner `/api/agent-sessions`：

- `q`：最多 96 字符，匹配规范化标题和 cwd basename；
- `period`：`all`、`today`、`7d`、`30d`；
- `archive`：`active`、`archived`、`all`；
- `location`：`all` 或当前目录/项目 scope；
- `page`：过滤后分页。

SQL LIKE 必须转义 `%`、`_` 和反斜杠；显式 rename 通过缓存的 session index 先得到候选
thread id，再与 SQLite metadata 条件合并。不得构造正文全文索引。

## 前端方案

- Session History 标题下增加 search field；
- chips：All、7 days、This folder、Archived；
- 250 ms debounce，旧请求 AbortController 取消，响应按 request generation 丢弃；
- 搜索时页码归 1；刷新保留 URL 中条件；清空恢复原分页；
- 无结果显示当前过滤条件，不显示“历史丢失”；
- Active Sessions 默认不受历史搜索隐藏，可提供独立的 `Active` filter。

## 测试矩阵

1. 450+ 条匿名 metadata，rename、重复标题、中英文、特殊 SQL 字符；
2. 标题、cwd basename、日期和 archived 单独及组合过滤；
3. 过滤后第一页/中间页/最后页与总数；
4. 快速连续输入、取消旧请求、刷新和浏览器返回；
5. 当前 workspace scope 与其他 route/user 不泄漏；
6. 页面不请求 rollout 正文，不把搜索词写 storage/log；
7. 390x844、1440x900、键盘和触控；
8. Start/Resume/Close、目录选择、发送、公式和 tmux 几何回归。

## 验收标准

- 已知标题或项目名在一次搜索内可定位；
- 结果总数、页数和实际卡片完全一致；
- 搜索不显著增加 Owner 内存或扫描大型 rollout；
- 公开 fixture 不含真实标题、路径或 thread id；
- 真实历史只输出计数和匿名匹配状态。
