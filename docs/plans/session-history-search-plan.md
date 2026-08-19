# Faryo Session History Search and Filter Plan

更新时间：2026-08-20
状态：完成并部署验证

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
- `page`：过滤后分页。

实际实现先由 SQLite 按 source、workspace、archive 和 active-thread exclusion 缩小元数据
集合，再在 Python 中对 title、缓存的显式 rename 和 cwd basename 做 Unicode
`casefold` 字面量匹配。因此 `%`、`_` 和反斜杠没有 SQL wildcard 语义，也不需要把 rename
回写数据库。不得构造正文全文索引。

没有增加客户端可控的 `location=all`：普通 Gateway 用户原本就被强制限定在配置的 workspace
root，允许页面放宽该范围会削弱隔离边界。目录定位由 cwd basename 搜索完成。

## 前端方案

- Session History 标题下增加 search field；
- chips：All time、Today、7 days、30 days，以及 Current、Archived、Any status；
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

## 实施与证据

- Owner 的筛选只读取 `state_5.sqlite` thread metadata 和缓存的 `session_index.jsonl` rename；
  测试显式证明 conversation-history reader 没有被调用。
- Owner 与 Gateway access log 只保留 HTTP method/path，query 中的搜索词、Token 和本机路径
  不落日志；过滤结果不写入 `sessionStorage`。
- 250 ms debounce、`AbortController`、request generation、URL query、空结果文案、页码归一和
  Active Sessions 隔离均已实现。
- `%_` 被按字面量目录名匹配；公开 fixture 覆盖 rename、目录、30 天、archive 和 96 字符上限。
- canonical source check 通过：Owner 72 项、Gateway 51 项及全部维护中的 JavaScript 测试，
  包括 455 条匿名 metadata 的组合过滤与分页。
- 本机真实 Gateway 在 390x844 Chrome 和 1440x900 Chrome 通过：搜索、清空、7 天切换、
  10 条分页、第 2/3 页、无横向溢出、Active 数量不变、过滤快照未持久化。
- 部署前后全部现有 tmux window geometry 完全一致；测试没有启动、关闭或修改 Codex 会话。
