# 数据、运维与扩展

[返回 README](../README.md)

## 数据与缓存

建议把 `/app/data` 持久化。这里会保存：

- SeerAPI / alias SQLite 缓存
- B站 Cookie 与动态状态
- 米米号样本排行 SQLite
- `data/state/qq_state.sqlite`：QQ 用户与群聊低频状态，包括默认米米号、查询额度、推送偏好、榜单显示条数和战队订阅
- `data/state/runtime_state.sqlite`：活动提醒、战队审核提醒、幸运橱窗等运行任务检查点
- 全服榜页 SQLite 缓存
- 阵容、AI 对话、B站动态历史、皮肤价格和渲染缓存等独立大数据

大型缓存按生命周期保持独立；不会为了减少文件数量而把榜单事实、阵容图片 Blob 或 AI
对话历史塞进共享状态库。

### 状态库迁移

只有仍使用旧小型 SQLite 布局的部署需要此离线迁移；已完成迁移的部署不必每次升级重做。
先停掉机器人，再用新镜像把旧的小型 SQLite 一次性迁移到两个共享状态库。
命令默认只预览；确认输出后再加 `--apply`。迁移会先完整备份旧库，校验行数、主键和
`PRAGMA integrity_check`，成功后才原子安装新库并移除旧库。

Unraid 默认数据挂载为 `/mnt/user/appdata/ironsbot/data`：

```bash
docker pull murmansk5000/ironsbot:latest
docker stop ironsbot

# 预览，不修改文件
docker run --rm --entrypoint python \
  -v /mnt/user/appdata/ironsbot/data:/app/data \
  murmansk5000/ironsbot:latest \
  -m ironsbot.state_migration --data-root /app/data

# 确认后执行
docker run --rm --entrypoint python \
  -v /mnt/user/appdata/ironsbot/data:/app/data \
  murmansk5000/ironsbot:latest \
  -m ironsbot.state_migration --data-root /app/data --apply

docker start ironsbot
```

备份默认位于 `data/state-migration-backups/<UTC时间>/`。稳定运行 7 天后可手动删除对应备份。
若 TOML 自定义了 `[paths].qq_state` 或 `[paths].runtime_state`，迁移时同时传入
`--qq-state` 和 `--runtime-state`；相对路径均以 `--data-root` 为基准。

迁移后从 TOML 删除以下旧字段；新版本不再读取它们：

- `activity.cache_path`
- `messaging.push_unsubscribe.data_path`
- `messaging.team_audit_welcome.followup_cache_path`
- `seer.player.binding.path`
- `seer.player.query_limits.path`
- `seer.rank.display_limit_path`
- `seer.team_resource.subscription_path`

`seer.player.lineup.cache_path` 不在收口范围内，阵容图片缓存仍保持独立。

主数据发布文件现使用 `data/seerapi-data.sqlite`。确认新版本已成功下载并能查询最新数据后，
旧的 `data/ironsbot-data.sqlite` 可手动删除；状态库迁移命令不会自动删除主数据文件。

超级管理员发送 `/更新数据`（别名 `/数据更新`、`/同步数据`）时，IronsBot 会先只读比较本地与已发布数据的指纹，再显示后续选项：

1. 同步已发布数据，不触发远程构建。
2. 检查上游、依次构建并同步数据。

`/强制更新数据`（别名 `/强制数据更新`、`/强制同步数据`）只会让第 2 项向支持的工作流传入强制构建参数。第 2 项使用
`[operations.data_sync.sources.seerapi.remote_build.steps]` 定义的 GitHub Actions 流水线：

1. `Murmansk-Seer/data-update-workflows`：检查淘米官方资源包，更新 Unity 资源和完整配置源。
2. `Murmansk-Seer/seer-unity-config-parser`：抓取官方 Unity ConfigPackage 并导出补充 JSON。
3. `Murmansk-Seer/config-sources`：同步上游配置源并检查官方版本。
4. `Murmansk-Seer/api-data`：用 Solaris 构建 SeerAPI 基础 SQLite。
5. `Murmansk-Seer/seerapi`：合并基础库、官方 ConfigPackage 补充表和自定义表，发布 IronsBot 运行库。

启用远程构建时，环境变量需要填写 `GITHUB_WORKFLOW_TOKEN`。默认情况下，启动同步和定时同步只下载
已有 release，不触发 Actions，避免容器启动过慢或频繁消耗 GitHub Actions。启动同步默认开启；
如不希望开机下载 release，可设置：

```toml
[operations.data_sync]
on_startup = false
```

若希望开机时近似执行一次 `/更新数据`，可同时设置：

```toml
[operations.data_sync]
on_startup = true
startup_trigger_remote_build = true
```

开机同步的成功、失败、无需更新状态会追加到“机器人已开启。”通知中。

## Docker 自更新与重启

超级管理员发送 `/重启机器人`、`/机器人重启`、`/更新镜像` 或 `/更新Docker` 会打开
统一维护菜单。选择 `1` 只重启当前容器或进程，不检查镜像；选择 `2` 检查并在需要时
启动独立的一次性 IronsBot 部署监督进程更新，然后完成重启。`/检查更新镜像` 仍只读检查，不执行更新。
检查结果会分别显示本机与 Docker Hub 镜像是否一致，以及镜像 revision 是否与源码仓库
GitHub `main` 对齐。缺少 revision 标签或无法访问 GitHub 时会标记为无法确认，不把
Docker Hub 镜像一致误判为代码已对齐。

这个能力需要把宿主机 Docker socket 挂进容器：

```text
/var/run/docker.sock -> /var/run/docker.sock
```

TOML 可调整检查时机、容器名、目标镜像和 Docker API 连接参数：

```toml
[operations.docker_update]
check_on_startup = true
image = "murmansk5000/ironsbot:latest"
container_name = "ironsbot"
docker_socket_path = "/var/run/docker.sock"
```

### 私有扩展包

公共镜像不包含阵容命令、协议解析、缓存或渲染实现。只有已安装且已验证的私有扩展包才会
注册该功能，并复用主机器人的精灵数据、头像资源和渲染器。

真实阵容来自可选私有扩展包 `murmansk5000/ironsbot-private:latest`。它不是机器人
覆盖镜像：Unraid 的 Repository 和 `[operations.docker_update].image` 始终保持
`murmansk5000/ironsbot:latest`。容器启动时，公开主镜像通过 Docker socket 拉取私有包、
校验其 `[project.entry-points."ironsbot.extensions"]` 工厂清单并解包到
`/app/data/private_extensions`，再显式调用工厂，传入公开的强类型 `ExtensionServices`。
导入模块本身不注册业务，扩展不能按字符串查找组合根的内部服务。

阵容是第一个扩展；以后可在同一个私有包中增加新的、由公开主程序显式支持的扩展。整个
部署仍只有一个 IronsBot 进程，并复用已配置公共无头账号池。扩展直接借用主连接发送封包，不启动
FastAPI、不暴露端口，也不需要第二个米米号或 API Token。

在 TOML 中启用私有扩展包：

```toml
[operations.private_extensions]
enabled = true
image = "murmansk5000/ironsbot-private:latest"
```

再在 Unraid 容器变量或 `.env.prod` 中设置 Docker Hub 的最小拉取凭据；不要写进 TOML：

```text
DOCKER_REGISTRY_USERNAME=murmansk5000
DOCKER_REGISTRY_TOKEN=private-image-pull-token
```

私有扩展包在公开主镜像启动前通过已挂载的 Docker socket 拉取，因此 Unraid 的 Repository
不需要改成私有镜像。Docker socket、上述两个容器变量，以及 `enabled = true` 都是必要条件；
首次拉取失败时会保留上一次成功安装的扩展；没有可用包时，阵容功能不会注册。

凭据缺失或私有镜像没有安装时，主机器人仍会正常启动，`阵容` 不会响应。
公共无头账号由 `[operations.headless].accounts` 中的账号引用决定；
每个账号密码使用 `SEER_PASSWORD_<player_id>`。每个账号独立连接，查询和刷榜可并行；
阵容功能复用公共账号池，不单独登录。

如果不想让机器人自然启动时检查镜像，可改为：

```toml
[operations.docker_update]
check_on_startup = false
```

自然启动检查任务注册在数据同步之前；如果发现新镜像，独立部署监督进程会重建容器，
本轮启动会被新容器替换。镜像通知会显示当前/最新镜像短号、北京时间构建时间，
并在镜像带有 OCI revision label 时附上对应 Git commit 摘要。
监督进程要求新容器 120 秒内完成启动，随后连续运行 60 秒，期间无重启、退出或 OOM。
验证成功后删除本次停止的回退容器，并清理确认属于公开 IronsBot 且未被任何容器引用的旧镜像；
验证失败恢复旧容器及本次修改的配置。清理失败只报告资源和原因，不回滚已验证的新容器。
不执行全局 prune、不强制删除、不删除挂载目录；其他容器引用、来源不明、私有扩展包及通用镜像不纳入公开镜像清理。
多标签和同源 GHCR 镜像按来源与引用核对，重复清理保持幂等。私有包自己的缓存与安装保留由扩展加载器管理。

没有挂载 Docker socket 时，容器镜像检查会跳过；Windows 源码运行可关闭启动检查。
`watchtower_image`、`watchtower_docker_api_version` 属于保留的历史配置，不再作为当前监督器的工作原理或 Docker 版本修复方案。
监督器、手动部署用法和恢复文件权限见[部署验证与清理](specs/2026-10-08-docker-verified-deployment.md)。

推送通知会按订阅项拆分，例如机器人启动、Docker 镜像检查、启动数据同步、
AI 聊天异常、B站登录、无头赛尔号、精灵渲染崩溃、红包提醒、按账号拆分的 B站动态和活动结束提醒。
私聊发送 `TD`，或群主/管理员在群里发送 `TD`，可以分别退订/恢复
这些推送；发送 `推送时间` 可修改可编辑推送的提醒时间。

游戏和别名数据实际更新成功后，仅向具有显式管理通知资格且未退订的超级管理员私聊发送简短通知，
不向管理群发送。通知显示数据生产方的生成时间（北京时间）；缺少可靠时间时显示“未知”，
不使用下载完成时间代替。首次安装静默初始化；已有安装重启后发现内容变化仍会通知。
两类更新通知可在私聊 `TD` 中分别控制。

SeerAPI 模型依赖跟踪 `Murmansk-Seer/seerapi` 的 `main`，实际版本由 `uv.lock`
记录的提交固定。更新时运行 `uv lock --upgrade-package seerapi-models` 并完成测试；
测试和镜像使用同一锁文件，运行中的容器不会在启动时自动升级依赖。

`.env`、`.env.dev`、`.env.prod` 和真实运行数据不应提交到 Git。

## 上游更新策略

本仓库已经是独立维护线，不再直接 merge 或 rebase
[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot) 的 `main`。
GitHub Actions 里的 upstream workflow 每天北京时间 **12:00** 检查上游，并保留巡检报告。
发现主分支尚未包含的上游提交时，创建附有提交摘要和链接的 GitHub Issue，
指派给仓库所有者；通知是否送达遵循个人 GitHub 通知设置。
同一上游最新提交只通知一次，关闭 Issue 后也不重复创建；上游再有新提交时另行通知。
该工作流使用仓库自带的 `GITHUB_TOKEN`（`contents: read`、`issues: write`），
无需另配密钥，仓库需开启 Issues。组织名下的 fork 应将脚本中的收件人改为可指派的成员。
定时运行以默认分支上的工作流为准，GitHub 调度可能延迟；也可以手动运行。
它不会自动合并、提交、推送或发布镜像。

处理上游更新时按类型选择性吸收：

- 小型 bug 修复：手动 port 到当前架构，或在确认冲突范围后单独 cherry-pick。
- 数据和别名更新：进入 SeerAPI / alias SQLite 数据构建流程，不在 bot 仓库恢复旧 CSV。
- 精灵查询、渲染、协议能力：按 `services` / `integrations` 边界吸收，不恢复原版用户入口。
- 上游结构性重构：默认不跟随，除非它修复了当前项目里的具体问题。

也就是说，上游现在是参考源和补丁来源，不是可以直接同步的主线。

## 本地开发与终端

```powershell
uv sync --group dev
uv run python scripts/check_repo.py
uv run python -m ironsbot
```

如果 Windows 终端中文显示异常，可以在当前 PowerShell 会话里先执行：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

快速只检查配置文件语法和 UTF-8/乱码扫描：

```powershell
uv run python scripts/check_repo.py --static
```

## 插件架构

通用用户功能位于 `ironsbot/plugins`，部署者自行维护的扩展位于
`ironsbot/custom_plugins`。当前版本仍由 `python -m ironsbot` 经过
`ironsbot/app/bootstrap.py` 启动。内置插件由 `app/plugin_composition.py` 显式装配；
full/core 使用同一份有序工厂目录，并以 `PluginContribution` 注册运行时
贡献。`CommandCatalog`/`CommandContract` 是用户命令、帮助、戳一戳提示和 AI
命令认领的唯一语义来源。

当前接入方式与公共执行链状态以[入口核对清单](onebot-menu-parity.md)为准，不把历史 matcher 包装视为扩展契约。私有扩展通过
Python 标准入口点声明工厂，只能取得公共代码声明的窄契约，不能成为内置插件发现或命令
注册入口。旧私有 NoneBot 清单不再加载；公共与私有包必须使用经验证的配对版本。
后续迁移方向、责任边界与完成条件以
[ARCHITECTURE.md](../ARCHITECTURE.md) 为准。

- 赛尔查询：玩家、战队、精灵、刻印、装备、属性、巅峰、群星牌和榜单。
- 消息与内容：固定文本、定时消息、固定图片、腾讯会议和帮助。
- 推送：B站动态、游戏活动、开服状态和战队资源。
- AI：聊天、提及保护、意图识别和模板动作。
- 运维：数据同步、无头登录、启动通知、定时重启和 Docker 更新。

## 配置校验

配置副本可执行 `python -m ironsbot.config_check --config /config/ironsbot.toml --no-dotenv`，
不会建立机器人连接、启动调度或修改业务库。源码本机需要加载 env 文件时去掉 `--no-dotenv`。
该命令会解析配置，不只是检查 TOML 语法；完整用法见[配置与启动校验](configuration-and-subscriptions.md#配置文件与启动校验)。

## 扩展动作与详细阵容

公共包不恢复旧 `PrivateExtensionRuntime` 或裸 QQ 参数 API。
扩展通过 `PlayerDetailActionRegistration` 声明动作，使用公共 `PlayerDetailActionRequest`、查询端口和投递结果。
访问约束、菜单可见性、数字目标及绑定建议通过公共声明控制；执行时复查实际操作者。
私有 details 的“阵容详情<数字米米号>”仅限超级管理员，不自动进入普通玩家菜单，群管理员不因此获得权限。
普通阵容仍走普通扩展行为；需要的特性、技能、刻印、素材与渲染通过类型明确的窄端口提供。
失败或元数据不完整不得补零伪装完整结果。详细分支发布前还须更新与公共提交配对的 public-runtime.json，
不能把本地测试通过等同于已发布版本兼容。experiments 只供历史参考，不参与运行注册。

## 原生图片渲染

图片继续使用同一个 litehtml 原生引擎，不需要浏览器。主仓库维护最小 Python 绑定，
字体初始化由应用启动负责，图片/CSS 网络访问复用应用 HTTP 客户端，不再加载 htmlkit 的
NoneBot 插件。现有 FONTCONFIG/FC 环境变量继续有效，没有新增 TOML 或 Unraid 字段。
为保持 ABI 与输出一致，原生二进制载体固定到已验证版本，更新时须连同锁文件、
原生 PNG 对照和主程序/扩展配对一起验收；不能单独升级该依赖或把它的存在视为
应用仍需要加载旧插件。来源及许可证见 `ironsbot/integrations/litehtml/NOTICE.md`。

[返回 README](../README.md) · [配置与订阅](configuration-and-subscriptions.md) ·
[玩家查询](player-query-guide.md)
