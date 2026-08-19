# Faryo Codebase Cleanup Plan

更新时间：2026-08-19
状态：已完成

## 目标

把个人 fork 收敛为实际维护和验证的 Ubuntu/Linux + Codex 单一生产路径，删除已经
不可达、被替代或退出支持范围的代码与资产，同时保持 Owner、Gateway、结构化历史、
Markdown/KaTeX/Shiki、可靠发送和项目工作台正常。

Git 历史不重写。删除内容仍可从清理前提交恢复，但不再进入当前 checkout、部署负载
或后续维护面。

## 删除准则

只有满足至少一项并能通过引用审计与回归验证的内容才删除：

1. 没有运行入口、文档入口或测试引用；
2. 已被当前实现完整替代，例如独立宠物帧已合并为雪碧图；
3. 不属于根 README 声明的支持范围，例如 Claude 和 macOS launchd；
4. 对应发布物不再构建、发布或验证，例如旧二进制打包器；
5. 静态分析确认只有定义、没有调用的薄包装函数。

## 本轮范围

- 删除 Claude 会话发现、启动/恢复、OAuth 配额、前端 compact rules 和 Gateway 入口；
- 删除 macOS launchd 安装器以及 Debian/macOS 二进制构建分支；
- 将仍在使用的源码检查从 `package-client.sh check` 收敛为 `check-source.sh`；
- 删除历史 UI 目标图、被雪碧图替代的独立宠物帧和重复状态脚本；
- 删除失去读取方的根/Gateway RELEASE 元数据和未链接的旧发布草稿；
- 删除已确认无调用的 Python 函数和关联 import；
- 删除本地可重建的 `node_modules`、`__pycache__` 与测试缓存，但不把缓存清理混同为
  Git 源码减重。

## 明确保留

- Gateway 的多 Owner 路由、项目工作台和文件投递；
- Codex 结构化 JSONL/App Server 读取与 tmux 终端证据；
- AST Markdown、KaTeX、Shiki 及其完整第三方许可证；
- 当前匿名宣传截图和浏览器回归 fixture；
- 历史 release notes，用于说明过去版本而非当前支持承诺；
- 动物停止按钮以及 Codex/tmux 原始终端尺寸。

## 验收

- 源码中除历史 release notes、DeepSeek Harness 归属和防回流断言外，不再出现 Claude、
  macOS launchd 或二进制打包入口；
- 源码检查、Owner/Gateway Python 测试、浏览器 Markdown/公式/布局测试、发送隔离和真实
  Codex 长会话测试全部通过；
- 部署前后所有真实 Codex tmux 窗口尺寸一致；
- 公开差异不含真实域名、邮箱、Token、Cookie、会话正文或本机私有路径；
- 文档记录最终删除文件数、源码体积变化和测试证据。

## 完成结果

- 跟踪文件由 230 个降至 213 个；删除 18 个文件、重命名 1 个检查脚本并新增本计划；
- 当前跟踪内容由 6,073,401 字节降至 5,467,932 字节，减少 605,469 字节
  （9.97%）；
- 本次差异删除 1,129 行、增加 166 行，净减少 963 行；
- 清除 47 MB 可重建 `node_modules` 以及 18 个 Python 字节码文件，工作区（不含
  `.git`）由约 54 MB 降至 5.9 MB；依赖可用 `npm ci` 恢复；
- `scripts/check-source.sh`、53 个 Owner Python 测试和 45 个 Gateway Python 测试通过；
- 手机与桌面 Markdown/KaTeX/Shiki、受保护资源、问题导航、20 条消息投递、附件、
  离线恢复、重启幂等和双会话隔离测试通过；
- 真实 Gateway 在 390x844 与 1440x900 下仅显示一个 Codex launcher，连续三页历史
  均按 10 条加载；真实 Codex 长会话仍显示 12 个问题导航标记；
- Owner 与 Gateway 已重启并健康，已退休静态资源返回 HTTP 404；五个真实 Codex tmux
  窗口在部署前后均保持 145x44；
- 公开差异隐私扫描通过，Git 历史保留，不做破坏性的历史重写。
