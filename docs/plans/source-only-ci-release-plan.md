# Faryo Source-only CI and v1.2.0 Release Plan

更新时间：2026-08-20
状态：实现完成，等待三项联合发布

## 问题基线

当前仓库已经收敛为 Ubuntu/Linux + Codex 的 source deployment，但发布链仍保留旧事实：

- `.github/workflows/release.yml` 只在 tag 上运行，没有 `main`/PR 持续集成；
- workflow 调用已经删除的 `scripts/package-client.sh`；
- workflow 仍试图生成已明确放弃的 deb 和 macOS 包；
- `scripts/check-source.sh` 直接调用裸 `python3` 和 `node`，不识别项目 Conda 环境或
  NVM；非交互 Shell 已真实复现 `node: command not found`；
- canonical source check 运行 Owner 测试但没有包含 Gateway 的完整测试集；
- `apps/owner/RELEASE` 和最新 tag 仍是 `v1.1.4`，没有覆盖当前完整历史、公式、命令、
  目录选择、复制、发送与安全加固。

## 目标

1. 建立 `push main`、pull request 和 release tag 共用的 source-only CI。
2. 唯一发布检查自动、可解释地选择 Python 与 Node，不依赖交互式 Shell 初始化。
3. 将 Owner、Gateway、JavaScript、portal template、静态资源和隐私源检查纳入同一入口。
4. 删除失真的二进制打包 workflow，不恢复已删除的打包脚本。
5. 准备并在全部三项产品化任务验收后发布 `v1.2.0` source-only GitHub Release。

## 运行时发现契约

### Python

优先级：

1. 可执行的 `FARYO_PYTHON`；
2. 当前 `CONDA_PREFIX/bin/python`；
3. 通过 Conda 自动发现名为 `faryo` 的环境；
4. PATH 中的 `python3`；
5. 否则给出明确错误和配置示例。

本机验证继续使用 `/home/.../envs/faryo/bin/python`，但公开脚本和 fixture 不写入真实用户
路径。

### Node

优先级：

1. 可执行的 `FARYO_NODE_BIN`；
2. PATH 中的 `node`；
3. 从 `FARYO_CODEX_BIN` 的 NVM 安装布局解析同版本 sibling Node；
4. 自动发现本机最新的 NVM Node；
5. 否则给出明确错误，不静默跳过 JavaScript 测试。

## CI 与发布方案

- 新增 source CI workflow：Ubuntu、Python 3.13、Node 24、Gateway requirements；
- pull request/main push 运行 `scripts/check-source.sh`，不需要 Token、Cookie、Cloudflare
  或真实 tmux；
- tag workflow 先复用同一检查，再核对 tag 与 `apps/owner/RELEASE`；
- GitHub Release 只使用 GitHub 自动生成的 source archive 和公开 release notes，不上传
  `.deb`、macOS tarball 或伪造的 endpoint package；
- `docs/releases/v1.2.0.md` 说明 source install、升级、回滚、安全边界和不兼容变化；
- release 只在三个产品化计划全部通过、main 已推送且工作树干净后创建。

## 测试矩阵

1. Conda/NVM 已加载、仅显式环境变量、仅 PATH、缺失 Node、缺失 Python；
2. 本机 `faryo` 环境与干净 GitHub Actions runner；
3. Owner/Gateway Python、全部维护中的 JS/browser source tests；
4. Portal JS 的源码态与 Python 运行态均通过语法检查；
5. tag/version 一致、release notes 存在、无旧打包命令；
6. workflow 不读取任何生产 secret；
7. 公开仓库隐私扫描、工作树和 remote main 一致。

## 验收标准

- `main`/PR 在 GitHub 上自动得到可复现的绿色检查；
- 本机未加载 NVM/Conda 初始化时仍能通过显式配置运行；
- release workflow 中不存在 `package-client.sh`、deb、macOS 包引用；
- `v1.2.0` release 页面、版本文件和说明一致；
- 不改变运行时认证、tmux、会话或用户数据。

## 实施与证据

- 新增 `scripts/runtime-env.sh`，按上述契约发现 Python 与 Node；公开脚本不包含本机路径。
- 新增隔离 fixture，覆盖显式配置、Conda prefix、Codex sibling Node 和错误配置拒绝。
- `scripts/check-source.sh` 现在统一执行 Owner 68 项、Gateway 50 项及维护中的 JavaScript
  测试，并验证 Python 3.11+、Node 20+ 与 `bcrypt`。
- 新增 `main`/pull request Source CI；tag workflow 已改为 source-only，且强制校验版本文件和
  release notes。
- 在 `PATH=/usr/bin:/bin` 且移除 Conda/NVM 环境变量后，canonical check 自动发现本机
  `faryo` Python 3.13.14 与 NVM Node 24.16.0，全部通过。
- 版本号、`v1.2.0` notes、tag 与 GitHub Release 有意延后到另外两项功能共同验收以后，
  以保证 tag 代表完整且可回滚的发布点。
