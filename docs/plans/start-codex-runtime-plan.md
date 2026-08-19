# Faryo Start Codex Runtime Plan

更新时间：2026-08-19
状态：排队中；等待 Full-History Navigation 完成后开始

## 已报告现象

Gateway 主页的 `Start Codex` 当前会报错，预期的后台 tmux/Codex 会话没有成功启动。
本计划先记录问题，不在全历史任务实施中途修改启动链，避免把两个故障的运行证据混在一起。

## 调查范围

按请求链逐层保留隐私安全证据：

1. 浏览器确认页、CSRF 请求和 `/api/agent/new` 响应状态；
2. Gateway 路由、允许命令、Owner 代理响应与超时边界；
3. Owner 服务环境中的 `FARYO_CODEX_BIN`、PATH、shell 与 Codex 可执行文件解析；
4. `tmux new-session` 的返回码、临时会话生命周期和 Codex 子进程是否真正进入就绪状态；
5. 最大活动会话限制、managed-session 标记和失败后的幽灵会话清理；
6. 桌面手工创建的 Codex tmux 不得被关闭、改名或改尺寸。

日志和测试不得记录 Token、Cookie、真实工作区路径、会话标题或对话正文。

## 修复原则

- 不通过放宽 CSRF、Owner Token 或 Gateway 鉴权绕过错误；
- 不依赖交互式 login shell 的偶然 PATH；
- 启动成功必须以 tmux 存在、Codex 进程存在和可输入状态为证据，不能只看 HTTP 200；
- 启动失败必须返回明确错误并清理部分创建的 tmux，不留下占用 agent limit 的空壳；
- 不自动加入 `--yolo`、跳过权限检查或修改用户既有 Codex 权限配置；
- 不调用 `resize-window`，不改变任何现有 tmux/TUI 几何。

## 测试矩阵

1. 正常启动、重定向到新 Owner 会话并显示结构化历史；
2. Codex 可执行文件缺失、不可执行和显式路径错误；
3. tmux 创建失败、Codex 立即退出和就绪超时；
4. 达到 agent limit 时不创建会话；
5. 重复快速点击只产生一次受控启动；
6. 手机与桌面 Gateway 浏览器确认流程；
7. 新会话关闭后资源和 managed 标记清理；
8. 现有发送、历史、公式和 tmux 尺寸回归。

## 验收标准

- 从主页点击 `Start Codex` 后创建且只创建一个 managed tmux；
- Codex CLI 真正运行、页面跳转正确、首条输入可正常提交；
- 所有失败分支返回可理解错误且无幽灵会话；
- Owner/Gateway 单元、浏览器和真实运行时测试通过；
- 完成后记录根因、修复提交和匿名证据，并移入 Completed。
