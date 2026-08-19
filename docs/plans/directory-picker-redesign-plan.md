# Faryo Directory Picker Redesign Plan

更新时间：2026-08-20
状态：已完成并部署；进入目录规模与浏览器兼容性维护

## 问题基线

当前 Start Codex 目录选择器把以下内容作为同一种卡片平铺：

- 使用当前目录；
- 上级目录；
- 配置 root；
- 最近目录；
- 当前目录的子文件夹。

在 390x844 手机视口中，重复的长路径和 `Root / Recent / Folder` 前缀占据主要视觉空间，
“使用当前目录”又与导航项竞争，导致主操作、当前位置和目录层级都不清楚。

## 目标

1. 顶部明确显示标题和当前位置面包屑；Folders 第一项用常见的 `..` 进入父目录。
2. “在此文件夹新建”固定在底部，不随目录列表滚动。
3. 最近目录、其他位置和子文件夹分组展示，不再使用一张平铺列表。
4. 最近目录默认最多显示 4 个，去除当前目录、父目录、root 和重复路径；允许展开全部。
5. 子文件夹只突出名称，完整路径不在每一行重复。
6. 提供当前页即时搜索；不做递归文件系统搜索，不扩大 Owner 的读取范围。
7. 保留默认最近 cwd、Owner 签名、Gateway 校验、Owner 二次根校验和 `faryoN` 幂等启动。

## 非目标与安全边界

- 不选择文件，只选择工作目录；
- 不创建、重命名、移动或删除目录；
- 不显示隐藏目录，不允许符号链接逃逸配置 root；
- 不把绝对路径写入 storage、日志或公开 fixture；
- 不修改任何现有 Codex/tmux 会话名称、进程或几何。

## 交互结构

```text
Choose working directory                    Search
~ / Code_for_Docker / current-project

Recent
  faryo                                               ›
  PPC-integrator                                      ›
  Show more

Folders
  ..                                  Parent folder
  apps                                                ›
  deploy                                              ›
  docs                                                ›

Locations
  Home                                                ›

Cancel                         Start Codex in this folder
```

手机使用接近全屏的底部 sheet；桌面使用居中、受限宽度的对话框。列表是唯一滚动区，标题、
面包屑、搜索和底部操作保持固定。

## 测试矩阵

1. 最近默认目录、父目录、root、子目录和空目录；
2. 最近项去重、最多 4 项、展开/收起；
3. 搜索匹配文件夹名与最近目录标签，清空后恢复分组；
4. 点击 Folders 中的 `..`、面包屑、recent/location/folder；
5. 固定主操作使用当前页面的最新签名 token；
6. 取消、点击遮罩和 API 失败不创建会话；
7. 390x844 Edge/Chrome 与 1440x900 Edge/Chrome，无水平溢出；
8. 真实选择目录 -> `faryoN` ready -> 跳转 -> 精确清理；
9. Owner/Gateway、发送、历史、公式、命令提示、复制与 tmux 几何回归。

## 验收标准

- 首屏不再出现混合的 `Use / Parent / Root / Recent / Folder` 平铺卡片；
- 当前路径和主要动作无需滚动即可识别；
- 手机截图中目录名称是主要视觉信息，重复路径显著减少；
- 所有安全校验与启动可靠性测试保持通过；
- 完成后记录桌面/手机截图、交互证据、提交和部署状态。

## 完成证据

- 专用 `directory-mode` sheet 已替换通用平铺 choices；标题、`..` 父目录、折叠面包屑、搜索和
  底部操作不参与列表滚动；
- 最近目录内部按规范化路径去重，并排除当前/父/root，首屏最多 4 个并可展开；子目录
  始终完整保留在 Folders，即使同一路径也作为 Recent 快捷入口出现；
- 当前页搜索可即时过滤 Recent、Locations 和 Folders，清空后恢复原分组；不发起递归
  API 或新增文件系统读取；
- 面包屑最多 4 项，中间层折叠为省略号，长 root 只显示目录名，不再露出半截绝对路径；
- 390x844 Chrome 与 1440x900 Microsoft Edge 截图人工检查通过，面板无水平溢出，主操作
  固定在可视区底部；临时截图已删除，未写入公开仓库；
- 浏览器自动化验证 `..` 返回上级、面包屑、搜索、Recent 展开、Cancel、固定主操作、内容过长
  时可滚动以及内容较少时不制造无意义滚动；
- 匿名重叠路径 fixture 验证同一目录在 Recent 中只出现一次、同时仍在 Folders 中出现
  一次；搜索该名称时两个入口和 `..` 均保持可用；
- 真实 Gateway 完成“选目录 -> Start Codex -> `faryoN` ready -> 页面资源就绪 -> 精确
  Close”，测试前后桌面 Codex 几何与既有会话集合一致；
- Owner 68 项、Gateway 50 项 Python 测试和 `scripts/check-source.sh` 全部通过；历史、发送、
  Markdown/KaTeX、命令提示、复制和启动幂等边界无回归。
