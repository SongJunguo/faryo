# Long Conversation Rendering Plan

状态：实施中

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

- 2026-08-21：根因复现完成；实施和回归验证进行中。
