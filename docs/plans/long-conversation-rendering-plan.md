# Long Conversation Rendering Plan

状态：已完成并部署为本机 v1.6.8 source candidate

维护补强：v1.8.6 增加快速滚动 scroll-seek 门禁和滚动写入账本

范围：Owner Compact Chat 的单会话历史、Markdown/KaTeX 富内容和问题导航

隐私：性能证据只记录计数与耗时；不记录会话正文、域名、Token、账号或本机私有路径

## 问题

结构化历史已经按 12 个完整 turn 分页，但浏览器过去会把每个已读取 turn 都永久展开为
完整 Markdown、KaTeX 和代码高亮 DOM。长回答可产生数万节点；继续向上加载时，新页面的
全部富内容在同一个渲染任务中插入，浏览器会短暂无响应。问题导航还会在每个滚动帧重新
测量所有已加载问题的位置，使规模增长后滚动成本继续上升。

## DeepSeek Harness 参考边界

本次专项审查固定在 DeepSeek Harness 提交
[`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`](https://github.com/deepseek-ai/deepseek-harness/tree/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e)。
采用其 Trajectory 长列表已经证明的四个契约：

- 完整逻辑索引与当前挂载窗口分离；
- 语义 key 在历史前插后保持稳定；
- 只挂载可见范围和少量 overscan，并复用测得高度；
- 浏览器测试同时证明前插锚点、全范围可达和挂载量有界。

Faryo 不复制 Harness 的 React/Cordis 应用壳，也不直接把
`@tanstack/react-virtual` 塞入现有手写 transcript。Faryo 当前真正膨胀的是每条消息内部
的 KaTeX/Markdown 后代，而问题 rail 和稳定外层 block 已经有产品语义。因此先采用更小的
边界：保留所有已加载 block 外壳和完整问题索引，只虚拟化富内容 body。若未来外层 block
达到数千条并成为实测瓶颈，再单独评估把 transcript 提升为 Preact + TanStack Virtual。

## 实施

1. 新增独立 rich-block controller：
   - 最新流式尾部立即渲染；
   - 旧消息先使用有界高度占位；
   - 进入视口 overscan 时按帧生成 Markdown/KaTeX；
   - 离开较远区域后保存实测高度并释放富 DOM；
   - 问题跳转先恢复目标问题及其回答。
2. 保留现有 source-faithful copy 元数据；富内容重新挂载后重新绑定 TeX/Markdown 来源。
3. 缓存问题位置，只在历史结构或消息高度变化时重新测量；普通滚动只做二分定位和两个
   marker 的状态更新。
4. 保持历史 cursor、完整问题 rail、实时尾部、普通刷新资产版本、认证与 tmux 几何不变。

## 验收

- 纯函数测试覆盖 eager tail、高度估计、可见恢复和离屏释放。
- 40-turn 匿名长 Markdown/公式 fixture：初始富 DOM 挂载有界，旧页仍可连续加载，首个
  问题跳转后公式正常，前插锚点误差不超过 3 px。
- 真实长会话只输出节点数、长任务耗时与请求数；不得输出正文。
- KaTeX、复制、Raw/Chat、问题导航、实时流与 source checks 全部通过。
- 部署后普通刷新即可取得新资产；服务与现有 tmux 会话保持健康且尺寸不变。

## 当前证据

- 2026-08-21：匿名 40-turn 长 Markdown/公式 fixture 在加载完整逻辑历史后只挂载
  5 个富正文、保留 75 个轻量占位；对话区约 2,580 个后代节点。24 次宽度/DPI
  变化的最长主线程任务为 0 ms，完整问题索引、首题公式恢复、3 px 前插锚点、
  Raw/Chat 和 tmux 几何均通过。
- 隐私安全的真实长会话探针在 4 倍 CPU 降速下，把完整遍历后的页面元素从约
  43,034 降到约 4,762，把同时挂载的 KaTeX 节点从 852 降到 97；连续跨屏尺寸
  变化的最长任务从约 1,330 ms 降到 98 ms。旧页载入最长任务为 312 ms，且加载
  完成后继续释放离屏富 DOM。
- Canonical source gate：Owner 199、Gateway 117、CLI 57 个 Python 测试通过，所有
  JavaScript、lint、格式、依赖、bundle 和浏览器模块检查通过。
- 版本化安装器已切换本机 v1.6.8；`faryo doctor` 为 22 OK、0 warning、0 failed，
  Owner/Gateway 活跃，所有既有 tmux 会话及窗口尺寸保持不变。经本机 Gateway 普通
  新标签页验证，v1.6.8 结构化历史、KaTeX 和桌面布局通过。

## v1.8.6 快速滚动维护

2026-08-22 的真实长会话复测发现，离屏释放虽然让静止后的富 DOM 保持有界，但快速连续
上滚仍会沿途触发 Markdown/KaTeX 恢复；这会让主线程在滚动期间产生长任务和丢帧。网络只
发生既定的两次历史分页请求，页面也没有调用音频播放、振动或输出 BEL 字符，因此听到的
提示音不属于 Faryo 主动声音；浏览器或操作系统在卡顿/输入饱和时给出反馈是当前最合理的
推断，但不把该推断写成已证明的声源。

本次设计参考三类成熟契约：

- DeepSeek Harness 的
  [observed-top ledger](https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/implemented/bug-fix/2026-08-06-reader-scroll-attribution-observed-top-ledger.md)
  记录程序写入的滚动位置，不把锚点恢复误判为读者滚动；
- React Virtuoso 的
  [Scroll Seek Placeholders](https://virtuoso.dev/react-virtuoso/virtuoso/scroll-seek-placeholders/)
  在速度较高时保留等高占位，停止后再恢复真实行；
- TanStack Virtual 的
  [chat virtualizer contract](https://tanstack.com/virtual/latest/docs/chat) 使用稳定 key、动态
  测量、尾部锚定和有限 overscan，其
  [Virtualizer API](https://tanstack.com/virtual/latest/docs/api/virtualizer) 也把 `isScrolling`
  与停止延迟作为一等状态。

Faryo 不因此重新引入此前未通过历史前插锚点门禁的外层 virtualizer。更小且与现有架构
相容的改动是：快速滚动时暂停富正文恢复，保持已经测量或估算的等高占位；连续静止 180 ms
后，每帧最多恢复一个当前可见正文；程序性的锚点补偿通过写入账本排除；到达绝对顶部后，
正文增高不得把读者推回历史中部。隐藏后仍留在优先队列的项同时被清理，避免以后无法恢复。

同一私有长会话仅输出匿名计数的 A/B 压测中，v1.8.5 在快速上滚期间发生 112 次富正文状态
变化、2 个长任务，最长活动帧约 100 ms；v1.8.6 source candidate 降为 6 次状态变化、0 个
长任务，最长活动帧约 17 ms，停止后 DOM 约 380 个节点。两侧都没有音频、振动或 BEL 调用。
浏览器探针、单元测试和公开文档均不保存正文、域名、Token、账号或私有路径。
