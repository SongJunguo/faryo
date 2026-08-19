# Faryo Start Codex Runtime Plan

更新时间：2026-08-19
状态：已完成

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
9. 工作站选择后必须显示最近目录与配置 workspace；浏览器篡改目录候选会被拒绝。

## 验收标准

- 从主页点击 `Start Codex` 后创建且只创建一个 managed tmux；
- Codex CLI 真正运行、页面跳转正确、首条输入可正常提交；
- 所有失败分支返回可理解错误且无幽灵会话；
- Owner/Gateway 单元、浏览器和真实运行时测试通过；
- 完成后记录根因、修复提交和匿名证据，并移入 Completed。

## 根因与完成证据

- 根因一：本机没有 zsh，Owner 却硬编码回退到不存在的 `/usr/bin/zsh`；tmux 创建请求
  可以先返回 0，随后会话立即退出；
- 根因二：`/api/agent/new` 使用 `wait_ready=False`，Gateway 因此把“tmux 命令已接受”
  错当成“Codex 已运行”，并跳转到已经消失的会话；
- Owner 现在按 `FARYO_AGENT_SHELL`、`SHELL`、zsh、bash、sh 顺序选择真实可执行 shell；
- 配置的 Codex 路径必须存在且可执行；NVM 的 `codex.js` 会和同版本目录中的 Node
  配对，避免 systemd/非 login shell PATH 找不到 Node；
- 新建和恢复请求等待最多 15 秒，只有检测到 Codex 子进程才返回成功；Gateway 上游
  超时相应扩展到 20 秒；未就绪会话被精确 kill，不占 agent limit；
- 新增 shell fallback、无效 CLI、真实进程就绪、超时清理和原有会话分页函数防冲突测试；
- 匿名隔离测试在完全没有 zsh 的 PATH 下通过 bash fallback，managed 标记与 Codex
  进程均可见，原有 tmux 尺寸不变；
- 真实 Gateway 请求在 0.853 秒内创建可见的 managed Codex tmux；验证状态后只清理该
  测试会话，原有六个 Codex tmux 的尺寸和会话均保持不变；
- 新 managed tmux 使用第一个空闲的 `faryoN` 名称；真实验证得到 `faryo1`，清理后
  不残留测试会话；
- Gateway 先显示工作站，再打开目录浏览器；默认目录来自按更新时间排序的最近会话，
  页面提供当前目录、上级、配置 root、最近目录和子目录，长列表在手机 sheet 内滚动；
- Owner 仅列目录并隐藏 dot 项，规范化绝对路径，拒绝 root 外路径和 symlink 逃逸；选择
  使用 Owner Token 派生的 HMAC，Gateway 拒绝伪造凭证，Owner 再校验配置 root；
- 本机私有 `FARYO_START_DIRECTORY_ROOTS` 设为 Ubuntu 用户目录；公开示例仍推荐收敛到
  代码与研究根目录，不公开本机路径；
- 真实目录启动验证确认默认 recent cwd、`faryo1` 名称、实际进程 cwd 和清理，伪造
  token 返回 HTTP 400，原有 tmux 尺寸不变；
- 62 个 Owner、48 个 Gateway Python 测试及手机目录 sheet、浏览器工作台、全历史和
  发送矩阵通过。

## 参考审查

- [DeepSeek Harness pinned revision](https://github.com/deepseek-ai/deepseek-harness/tree/47f943859bef60e4160492346772ded9b24f765a)
  的 Web UI 没有可直接复用的目录 picker；采用的是“调用目录为默认 workspace、会话
  cwd 规范化后不可变、不可进入目录立即失败”的运行时边界；
- [OpenHands workspace API](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-agent-server/openhands/agent_server/workspaces_router.py)
  将 workspace/parent 真值保存在 agent server 并跨浏览器共享，而不是写 localStorage；
- [JupyterLab file browser](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/src/index.ts)
  提供 open directory、go up、可编辑路径、隐藏项策略与状态恢复；Faryo 采用其中的
  当前路径/上级/root/目录列表结构，但不引入其框架、文件操作或上传能力。
