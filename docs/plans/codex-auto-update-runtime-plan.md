# Codex 动态运行时与自动升级计划

更新时间：2026-08-21
状态：已完成、部署并通过 v1.6.5 发布门禁

## 问题

Faryo 的 systemd/tmux 环境不会自动加载交互式 NVM 初始化。旧实现把安装时发现的
`FARYO_CODEX_BIN` 长期保存，并通过同一 NVM 目录中的绝对 `node + codex.js` 启动。
这能避免 systemd PATH 缺失，却有两个产品问题：

1. NVM default 切换或旧 Node 目录删除后，持久路径会失效；
2. Codex TUI 的升级流程调用 npm 后要求重启，即使升级成功也不能保证原来的新会话继续打开。

## 目标

1. 每次新建、恢复和 App Server 重启都重新解析当前 Codex 安装；
2. 新安装不持久化某个 NVM 版本路径；旧自动生成路径只作最后兜底；
3. 支持 NVM recursive alias，例如 `default -> lts/* -> lts/name -> vX.Y.Z`；
4. 仅当用户显式设置 `FARYO_CODEX_BIN_PINNED=1` 时才固定路径；
5. Faryo-managed Codex 在 TUI 启动前检查官方 npm 最新版本并自动升级；
6. 更新失败或超时仍启动已安装版本，不让更新提示吞掉会话；
7. 更新后重启共享 App Server，并按新版本刷新私有 slash-command inventory；
8. 不修改既有 tmux 几何、对话、全局 Codex 配置或浏览器认证。

## 技术结构

```text
Start / Resume
  -> dynamic Codex discovery
       NVM default -> service PATH -> stable user paths -> newest NVM -> legacy hint
  -> one-launch absolute runtime snapshot
  -> locked update preflight
       cached check -> fixed official npm package -> verify installed version
  -> launch Codex with startup update prompt disabled
  -> reconcile App Server + command catalog if binary changed
  -> normal Faryo readiness monitor
```

自动更新：

- 默认启用，可用 `FARYO_CODEX_AUTO_UPDATE=0` 明确关闭；
- 检查结果使用 mode-600 状态文件并按小时复用；
- NVM npm 安装仅查询和安装固定包 `@openai/codex`，不接受浏览器提供的包名或 URL；
- 文件锁串行化并发启动；检查 15 秒、安装 180 秒硬超时；
- 自动更新失败仅产生通用提示，不记录 npm 输出、工作目录、会话标题或消息内容。

## 验收

- 动态解析覆盖 NVM alias、旧路径兜底、显式 pin 和缺失 pin；
- 最新版本不重复安装，新版本只安装一次，并发启动复用结果；
- 更新失败/超时后现有 Codex 仍启动；
- 新建和恢复命令均带更新预检，TUI 不再显示升级菜单；
- 0.149.0 的 46 项真实 slash inventory 与公开 fallback 完全一致；
- 更新后 App Server/命令目录只重载一次；
- 真实 Gateway 新建 -> ready -> 页面打开 -> 精确 Close；
- 普通刷新、Markdown/TeX、发送、历史、交互和 tmux 几何无回归；
- 完整 source gate、Python 3.10/3.13 CI、tag、Release 与资产校验通过。

## 完成证据

- Codex 0.149.0 的本地诊断确认：旧失败源于非交互服务 PATH 找不到匹配 NVM npm；
  动态解析现在跟随 recursive NVM default，旧自动生成路径仅为 fallback；
- 真实 NVM 预检确认 installed/latest 均为 0.149.0，状态和锁文件权限均为 600；
- 可升级、已最新、安全缓存、安装失败、预检异常仍 exec、App Server 单次重载和显式 pin
  均由匿名单元测试覆盖；
- 隔离 PTY 对 Codex 0.149.0 的 46 项命令完整盘点通过，现有 tmux 几何不变；
- 真实 Owner 新建会话达到 Waiting，自动更新状态为 Current，首条消息前使用 `codex-empty`
  而不是终端 fallback，随后精确 Close；
- 真实 Gateway 手机视口完成选目录、新建、GPT/Codex ready、普通资源加载和精确清理；smoke
  不再把页面资源 ready 冒充 agent ready；
- 本机 source gate 为 195 Owner、115 Gateway、56 CLI 测试，服务 Doctor 22/22；部署前已有
  tmux 的 pane PID 与几何未被 Faryo 更新操作改变。
