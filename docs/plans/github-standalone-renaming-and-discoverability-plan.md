# Faryo GitHub Standalone Rename and Discoverability Plan

更新时间：2026-08-20
目标仓库：`SongJunguo/faryo-codex-web-ui`
目标本地目录：`faryo-codex-web-ui`
状态：完成并部署

## 1. 决策

把当前公开 GitHub fork 永久脱离原作者的 fork network，并将独立仓库与本地项目目录统一改名为
`faryo-codex-web-ui`。

命名边界：

- 项目展示名：**Faryo Codex Web UI**；
- 独立品牌与界面短名：**Faryo**；
- GitHub slug 与本地源码目录：`faryo-codex-web-ui`；
- CLI、Python package、用户数据目录和 systemd units 继续使用稳定的 `faryo` 名称；
- README 首屏明确这是独立社区项目，不隶属、不代表、也未获 OpenAI 背书；
- 原作者仓库继续作为本地 `upstream` remote，并在 README 保留清晰归属。

不改 CLI/服务/数据名称，可以避免已有安装、配置、Cookie、systemd、更新链和 tmux 会话因营销性改名
发生迁移。

## 2. 为什么需要脱离 fork network

GitHub repository search 默认排除 forks；用户必须主动添加 `fork:true` 或 `fork:only` 才能看到。
当前实测：

- 普通 `faryo in:name` 搜索没有返回本仓库；
- `faryo in:name fork:true` 可以找到本仓库；
- `topic:codex topic:tmux topic:katex fork:true` 中本仓库为唯一结果；
- 外部搜索优先展示原作者仓库，而不是当前功能更完整的维护分支。

README、description 和 topics 可以改善分类与点击后的理解，但不能绕过 fork 默认排除。因此，如果目标
是成为可独立发现和使用的项目，脱离 fork network 是必要步骤。

## 3. 永久影响与已授权边界

GitHub 官方的 Leave fork network 是永久操作，不能重新连接原 fork network。Git commits 会保留，
但以下 metadata 不保证保留：

- issues、pull requests、comments、discussions 和 wiki；
- stars、watchers 与 child forks；
- Releases、Actions 历史与部分仓库设置；
- 其他不属于 Git refs 的平台 metadata。

执行前基线为：公开仓库、小于 1 GB、没有 child fork、没有 issue/PR、1 个 star、7 个 Releases。
用户已明确接受永久脱离和 metadata 重建。

禁止使用“删除 fork 后手工新建再 mirror push”的高风险备用流程，除非官方 Leave fork network 不可用
且再次获得明确授权。

## 4. 脱离前恢复包

在仓库外的私有备份目录保存：

1. `git bundle --all`，覆盖本地 branches、tags 和可达 commits；
2. `git show-ref` 与 origin/upstream remote 记录；
3. repository REST metadata、topics、description、默认分支和功能开关；
4. 全部 Release JSON 与 v1.5.0 的四个自定义资产；
5. Actions run 列表、Actions secret 名称、variables、environments；
6. hooks、deploy keys、collaborators 等可恢复设置；
7. 所有备份文件的 SHA-256 清单，并执行 `git bundle verify`。

恢复包不得进入公开仓库，不得记录 OAuth token、Cookie、密码、真实对话或私有部署域名。

## 5. GitHub 操作顺序

1. 确认 main 与 origin/main 相同、tag 列表完整、工作树干净；
2. 确认最新 main CI 成功；
3. 从 Settings / General / Danger Zone 执行 **Leave fork network**；
4. 等待 GitHub 完成转换，确认 repository API `fork=false`；
5. 将独立仓库重命名为 `faryo-codex-web-ui`；
6. 确认旧 URL 的 GitHub redirect，再把本地 `origin` 改为新 SSH URL；
7. 恢复 description、topics、issues/discussions 开关、安全扫描和默认分支；
8. 如 Releases 消失，按 tag 与仓库内 release notes 重建 7 个 Releases，并重新上传 v1.5.0 四个
   checksum/source installer assets；
9. 重跑 main CI，并记录新的 run URL。

## 6. 代码与文档迁移

全仓区分三类名称：

### 保持 `faryo`

- CLI entry point 与 Python package；
- `~/.faryo` 与 `~/.local/share/faryo`；
- `faryo-owner.service`、`faryo-gateway.service`；
- HTTP header、Cookie、配置键、审计 schema；
- UI 短品牌和 logo。

### 改为 `faryo-codex-web-ui`

- GitHub clone/release/badge/source URLs；
- updater 与 bootstrap 默认 GitHub repository；
- 维护中的安装、发布、安全和架构文档；
- 本地 checkout 目录。

### 兼容旧路径

- GitHub rename redirect 必须实际返回成功；
- v1.5.0 中硬编码的旧 release URL 必须能跟随 redirect 下载新仓库的资产；
- 新版本 updater 使用新 repository 常量；
- 历史 release notes 可保留当时路径，但不能成为当前安装入口；
- README 继续引用原作者仓库并说明来源，不伪装成原创初始项目。

## 7. GitHub 可发现性

README 首屏必须自然覆盖，而不是堆砌关键词：

- Codex CLI Web UI；
- self-hosted agent workbench / agent UI / session harness；
- tmux-backed sessions；
- mobile and desktop / PWA；
- Markdown、LaTeX、KaTeX；
- reliable delivery、structured history、remote access。

仓库使用不超过 20 个准确 topics：

```text
agent-harness, agent-ui, ai-agent, cloudflare-tunnel, codex, codex-cli,
coding-agent, katex, latex, markdown, mobile, mobile-web, openai-codex,
pwa, python, remote-access, self-hosted, terminal, tmux, web-ui
```

产品展示名包含 Codex 时，首屏同时显示 Faryo 自有品牌与非官方说明，不使用 OpenAI logo，不暗示合作、
认证或官方支持。

## 8. 本地目录重命名

GitHub 转换、代码引用与远端恢复完成后，把 checkout 从 `faryo` 改为
`faryo-codex-web-ui`。执行前：

- 枚举 cwd 位于旧目录的进程与 tmux panes；
- 确认生产 Owner/Gateway 使用版本化安装目录而不是 checkout；
- 确认没有构建或 Git 写操作正在进行；
- 保存旧绝对路径和新绝对路径检查结果。

执行后：

- `git status`、origin/upstream、branch、tag 和 worktree 正常；
- 新目录下 canonical source gate 通过；
- 旧目录不存在；
- 已部署 `faryo` CLI、Owner/Gateway 和所有 agent tmux geometry 不变；
- 编辑器或旧 shell 需要时只重新打开新目录，不创建兼容符号链接来永久保留旧路径。

## 9. 验收矩阵

### Git 与 GitHub

- repository API：`fork=false`、slug 正确、default branch=`main`；
- origin 指向新 SSH URL，upstream 仍指向原作者；
- local main、origin/main SHA 一致；
- 所有 tags 仍可达，v1.5.1 Release 和四个资产可下载并通过 SHA-256；
- settings/topics/description/security switches 符合备份；
- main CI Python 3.10/3.13 成功。

### 搜索与链接

- 不带 `fork:true` 的 `faryo-codex-web-ui in:name` 能找到仓库；
- `codex web ui`、`codex tmux`、`agent harness` 与 topic 组合记录初始排名；
- 旧 GitHub URL、旧 release URL 与 v1.5.0 updater 兼容检查成功；
- 外部搜索索引存在延迟，只记录当前可见性与后续复查入口，不伪造立即排名。

### 产品与部署

- Python 3.10/3.13 canonical source gate；
- `faryo doctor` 20 项检查无 error；
- Owner/Gateway active、loopback、Cloudflare 未被本任务修改；
- 真实手机/桌面工作台与 Markdown/KaTeX 代表性检查；
- 所有既有 Codex tmux session 与 geometry 不变；
- 不改 `~/.faryo`、Codex rollout/SQLite、附件或认证数据。

## 10. 完成条件

只有同时满足以下条件才把计划改为完成：

1. 官方 Leave fork network 成功且 `fork=false`；
2. GitHub 与本地目录均为 `faryo-codex-web-ui`；
3. 维护中链接/updater/bootstrap 全部迁移，旧版本更新链仍可用；
4. metadata、Release、资产和安全设置恢复；
5. README 与 GitHub About/topics 已优化且非官方说明清楚；
6. source、CI、release、部署、浏览器、tmux 与搜索验收通过；
7. main 推送完成、工作树干净，并在本计划附上不含隐私的最终证据。

## 11. 当前证据

- README 首屏已经加入描述性 H1、release/CI/Python/license badges、Codex Web UI、agent
  workbench/session harness、tmux、Markdown/LaTeX/KaTeX、mobile/PWA 与 quick links；
- GitHub description 已更新，topics 已扩展至准确的 20 个上限；
- 本地 canonical source gate 通过：Python 3.13.14，Owner 130、Gateway 112、CLI 51，前端与浏览器
  bundles 全绿；
- 私有恢复包已完成：verified all-refs bundle、repository/releases/Actions/settings JSON、v1.5.0
  四个资产与总 SHA-256 清单；
- 官方 Leave fork network 已执行；repository ID 保持不变，API 为 `fork=false`、`parent=null`、
  `source=null`。GitHub 实际保留了原 1 个 star、7 个 Releases、Actions history、topics、description、
  issues/projects/discussions 开关和 security scanning，比官方最坏情况警告更完整；
- 独立仓库已重命名为 `SongJunguo/faryo-codex-web-ui`，default branch 为 `main`。origin 使用新 SSH
  URL；原作者公开 URL 当前返回 404，本地仍保存 `upstream/main=625d8ce`、原 URL fetch 记录和
  `no_push` push URL，并在 README 提供本项目内可访问的 preserved baseline 链接；
- 旧仓库 URL 返回 GitHub redirect，旧/new repository、Release asset 与 API 路径均为 HTTP 200；
  未修改的 v1.5.0 updater 使用旧 repository 常量，已真实下载并安装新独立仓库的 v1.5.1；
- 本地 checkout 已改名为 `faryo-codex-web-ui`，旧目录不存在。重命名前后 faryo2 均为 145×44，
  并自动把 process cwd 解析到新目录；其他三个 tmux panes 的 cwd 与 geometry 不变。Owner/Gateway
  始终从版本化安装目录运行；
- 目录改名暴露并修复了一个真实产品回归：首个 Recent cwd 失效时，工作台现在依次尝试其余 Recent，
  最后才回退 root。真实首项 `faryo` 已不存在、第二项有效的 390×844 fixture 通过目录父级、搜索、
  Start controls 与三页历史验收；
- 无 `fork:true` 的 GitHub 搜索已生效：精确 slug 第 1/1，`codex+tmux+katex` topics 第 1/1，
  `codex+katex` 第 4/7，精确 `Codex CLI Web UI` 第 5/9，`faryo in:name` 第 14/16。宽泛词排名仍受
  stars/外链/使用量影响，不以关键词堆砌伪造曝光；
- 独立仓库 main Source CI `32379722500` 成功；v1.5.1 Release workflow `32379869459` 在 1 分 5 秒
  内完成 canonical gate 与四资产发布。源码 archive、archive SHA-256、bootstrap 和 bootstrap
  SHA-256 下载后均通过 strict checksum；
- 正式 v1.5.1 release-archive 已部署到 Python 3.10.12 private venv；doctor 20 ok、两个 services
  active/NRestarts=0，Cloudflare cookie-free verifier 保持 `access=PASS`，所有 tmux geometry 不变；
  本地候选备份已移入回收站，v1.5.0 作为 previous version 保留；
- 计划第 10 节全部条件已满足，进入维护状态。外部搜索引擎刷新存在延迟，后续只需观察索引和用户采用，
  不属于本次迁移阻塞项。
