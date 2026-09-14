# 重构交接与使用指南

快照日期：2026-09-14。用户要求暂停实施、整理交接并 push。
本文是接手入口，不另立架构规范，也不把历史构建成功当作真实平台验收。

## 1. 当前状态

- 总进度 `[#######-] 7/8`：阶段 0 至 6 的历史验收见阶段账本；阶段 7 未关闭。
- main 跟进清单已到 17/17（源码验证）。最后核对的 `origin/main` 为 `55a39fd1`，已包含在工作分支中。
- 公共源码最近全量：3589 passed / 7 skipped，2889 条依赖告警；Ruff、BasedPyright、compileall、diff 检查通过。
- 私有扩展对公共候选联合测试：45 passed / 1 skipped。原生渲染跳过不能当成通过。
- 未完成的独立官方版本发布门：同一精确镜像的真实连接、C2C 文本/查询/图片、群消息矩阵。
- 当前没有本任务保持运行的机器人测试进程。不要依据聊天中的“已启动”假定服务还在。
- 本轮暂停不等于完成。Docker 恢复后，操作验收估计 15–30 分钟，另加等待用户发送消息、平台权限处理的时间；没有可靠的整体完成 ETA。

## 2. 仓库与版本

三个本地仓库当前分支均为 `codex/multiplatform-architecture-v5`。

| 仓库 | 本机位置 | 本次文档提交前 HEAD |
| --- | --- | --- |
| IronsBot | `C:/Users/huime/.codex/worktrees/01bf/IronsBot` | `c14507f8` |
| seerapi | `C:/Users/huime/Documents/Code/seerapi` | `56878c3` |
| ironsbot-private | `C:/Users/huime/Documents/Code/ironsbot-private` | `4dce691` |

公共工作树远端：`origin` 是生产 IronsBot，`qq-official-preview` 是私有预览仓库。
当前公共分支推送目的地为：
`https://github.com/Murmansk5000/IronsBot-QQ-Official-Preview.git`。
私有扩展 `4dce691` 已推送其私有 origin 同名分支。
seerapi 的发布链应重新检查远端和对应 release，不从本机 HEAD 推断其发布完成。
私有扩展工作区有既存未跟踪 `uv.lock`，不要擅自提交或删除。

使用另一个工作树接手时先运行 `git status --short --branch`、`git remote -v`、
`git log -1`。不要把生产 main 重置成 V5，也不要删除旧工作树来解决分支占用。
读入 main 更新时先 fetch 和比较；合并有行为变化时补充 spec 和回归记录。

### 已发布候选

运行时代码：`e0aaeb125b3d82a2bc17dd98772f5238898e7c71`。
后续 `c14507f8` 和本次交接提交仅修改文档，不需要因此重建镜像。

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:c950a5e02c901c5c0db560e0f6b2e8babc4a9cac5e2a967c754f478fe639fc52
```

[构建 34852716528](https://github.com/Murmansk5000/IronsBot-QQ-Official-Preview/actions/runs/34852716528)
已通过依赖审计、Linux 构建、隔离网络 smoke、体积预算和 GHCR 发布。
Docker Hub 登录被跳过，未改公开生产镜像。
展开体积 259748177 字节（约 247.7 MiB），比固定基线多 9324 字节；
`/app` 4480 KiB、site-packages 105948 KiB、字体 19452 KiB。
这是展开体积，不是下载流量。后续瘦身不得靠删除正常功能、字体或错误处理伪造收益。

## 3. 技术路线与边界

权威材料按以下顺序阅读：

1. [ARCHITECTURE.md](../ARCHITECTURE.md)：目标契约、过渡边界、800 行限制、依赖方向。
2. [工程工作流](engineering-workflow.md)：spec 驱动、提交和验证要求。
3. [阶段账本](multiplatform-refactor.md)：分阶段的完成证据；早期记录不是当前实现。
4. [Spec 索引](specs/README.md)：按具体变更查契约，不复制另一份设计。
5. [官方真实验收](specs/2026-09-14-qq-official-live-acceptance.md)：唯一的当前发布验收记录。

当前主链路：

```text
python -m ironsbot -> app/bootstrap -> composition + application lifecycle
OneBot -> NoneBot adapter/matcher -> shared command/service
QQ Official -> Tencent SDK runtime -> portable router -> shared command/service
service -> portable reply -> platform outbound messenger -> delivery receipt
seerapi build -> versioned SQLite/resource facts -> repositories -> render view model
```

- 命令契约负责输入认领、权限和帮助；AI 不应抢已注册命令。别名、米米号和直接 @ 复用统一解析。
- 身份按平台、作用域和 AppID 隔离。OpenID 不能当 QQ 号，C2C 与群成员 OpenID 不能自行合并。
- 成功回调必须以送达回执为准。缺失回执、部分成功或不确定投递不自动重发，也不发送备用文字。
- 专属效果关联、魂印与官方资源正规化在 seerapi 构建端；机器人消费发布数据和 PNG，不重新引入 SWF 转换或硬编码图标名单。
- QQ/群小状态与任务状态分别使用共享状态库；大型玩家、榜单、阵容缓存按生命周期独立。旧状态只用一次性迁移工具处理，不加入运行时双读。
- 私有阵容和橱窗不是公共镜像内置能力；扩展只能使用公共端口，不能依赖公共插件内部实现。

核心实现入口：`ironsbot/integrations/qq_official/runtime.py`、`sdk_client.py`、
`outbound_messenger.py`，`ironsbot/services/portable_commands.py`、`portable_reply.py`。
最近两个重要修复为 `3fcfbcee`（可选 observer 隔离）和 `e0aaeb12`（不确定投递禁止备用重发）。

### NapCat 仅为可选增强

官方机器人可以完全独立运行，不要求 NapCat、真实 QQ 号或共同群。
`[bot] onebot_observer = true` 只提供 OneBot 入站业务隔离和底层 API 只读白名单：
不发送、不写入、不执行普通业务 matcher；默认 false，不影响原独立 OneBot 部署。
这个开关尚未实现“QQ 号与 OpenID 的可靠关联”。禁止用昵称、文本和时间猜测身份。
后续可单独做经验证的身份连接，但不能把它追加为官方独立版本的发布门槛。

## 4. 最小本机运行

需要 Python 3.11+、uv、有效 AppID/AppSecret，以及应用真实的 C2C/群 @ 和图片权限。
以下使用假账号别名。不要把历史会话中的凭据抄入仓库，已暴露的凭据应轮换。

把以下内容放入独立的本地 `config/ironsbot.toml`，不要覆盖已有生产配置。
该配置只开放验收功能，不是全功能生产 TOML。

```toml
[bot]
environment = "dev"
host = "127.0.0.1"
port = 18080
plugin_manifest = "core"
onebot_observer = false

[bot.qq_official]
enabled = true
sandbox = false

[bot.qq_official.accounts.example_bot]
enabled = true
app_id = "YOUR_APP_ID"
proactive_messages = false
features = ["help", "about", "seer_data", "seer_pet"]

[operations.docker_update]
check_on_startup = false

[operations.startup_notice]
enabled = false

[operations.clock_check]
enabled = false

[operations.data_sync]
on_startup = true
startup_trigger_remote_build = false
interval_enabled = false
```

`sandbox` 必须匹配实际应用环境。启动同步只是拉取配置中的发布数据，不触发上游构建。
全新目录的默认数据源未必已发布 V5 所需 schema；检查同步日志和 schema 校验结果，
必要时指定本次 seerapi 对应发布源。不要关闭 schema 校验，也不要冒用生产旧库。
关于/帮助连通不代表精灵/图片所需数据已经就绪。

PowerShell（先从自己的密钥管理方式安全注入环境变量，不在终端历史写明文）：

```powershell
uv sync --extra qq-official
$env:APP_CONFIG_PATH = (Resolve-Path config/ironsbot.toml).Path
# 运行前设置 QQ_OFFICIAL_SECRET_EXAMPLE_BOT；不要打印其值。
uv run --no-sync python -m ironsbot
```

Linux/macOS 同样执行 uv 命令，使用 `export APP_CONFIG_PATH=...` 设置路径。
不是必须 Docker；但源码运行不能代替精确候选镜像的发布验收。
当前凭据只需要 AppID 和 AppSecret，不需要旧静态 Token，也不是 nonebot-adapter-qq。
默认相对路径在工作目录下生成 `logs`、`cache`、`data`，可由 `[paths]` 覆盖。
WebSocket 主动连出不需要公网回调地址；纯官方测试不要暴露 OneBot 端口。

## 5. 精确候选 Docker 运行

先确认 `docker version` 有 Server 部分。需要私有 GHCR 拉取权限，可使用安全凭据方式
`docker login ghcr.io`，不要把访问令牌写入本文或提交。
在专用测试目录准备上面的 `config/ironsbot.toml`，并创建独立 data/cache/logs 目录。
不要挂载生产状态，不挂 Docker socket，不使用生产 main 的 `latest`。

以下为 Unraid/Linux shell 示例，先设置 `QQ_OFFICIAL_SECRET_EXAMPLE_BOT` 环境变量：

```bash
IMAGE='ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:c950a5e02c901c5c0db560e0f6b2e8babc4a9cac5e2a967c754f478fe639fc52'
docker pull "$IMAGE"
docker run --rm --name ironsbot-official-acceptance \
  -e APP_CONFIG_PATH=/config/ironsbot.toml \
  -e QQ_OFFICIAL_SECRET_EXAMPLE_BOT \
  -v "$PWD/config:/config:ro" \
  -v "$PWD/data:/app/data" \
  -v "$PWD/cache:/app/cache" \
  -v "$PWD/logs:/app/logs" \
  "$IMAGE"
```

此命令前台运行且不映射端口；第二个终端执行 `docker stop ironsbot-official-acceptance` 停止。
Docker 环境变量仍可被有 Docker 管理权的用户查看，不能视为专用 secret vault。
避免同一 AppID 同时启动多个测试实例。验收日志、Resume session 和状态挂载目录不提交 Git。

## 6. 使用与验收

最小配置开放：帮助、关于、数据版本、赛季倒计时、下周预告、精灵查询。
发送重名查询后直接输入数字，`0` 退出；官方引用回复当前忽略。
完整功能列表与 feature 示例见 README 和 config.example.toml，不代表所有应用权限均已实测。
数字 QQ、群号不能填到官方 `superusers`、group_policy 或 user_policy 中冒充 OpenID。

按照真实验收 spec 逐项测试同一 digest：

| 测试 | 预期 |
| --- | --- |
| 新启动或恢复连接 | 收到 READY/RESUMED 对应 connected 日志，无鉴权失败/重连风暴 |
| C2C 关于 | 一条文本回复 |
| C2C 精灵雷伊 | 共享查询正常结果 |
| C2C 下周预告 | 图片上传且实际送达 |
| 群直接 @机器人 帮助 | 本群一条帮助回复 |
| 群不 @ 的帮助 | 没有获准并支持普通群事件时不响应 |
| 官方引用回复 + @ | 不执行业务 |

主动推送默认关闭，只有部署确实需要时再验收主动权限、一次送达及退订抑制。
记录脱敏时间、候选 digest、API 送达结果及用户看到的结果，不记录秘密或原始 OpenID。
已有源码 fresh READY 和两条群事件处理证据；handler 返回不证明发送成功，不能勾选表格。

### 当前宿主阻塞

9 月 14 日末次检查：Ubuntu WSL Running，docker-desktop Stopped；Docker Desktop CLI
显示界面已运行，但 Server 探测 10–15 秒超时。后台日志记录 9 月 13 日 Inference manager
无法访问 `AppData/Local/Docker/run/dockerInference` 后关闭引擎。
这解释当前宿主状态，不是 IronsBot 异常，也不能保证重启一次就解决。
仅终止了本任务自己的超时探针；未重置 Docker、删除 socket 或磁盘、停止他人进程。
恢复引擎或使用另一个获授权的 Docker 主机后继续，不反复新建文件/重建相同镜像来代替验收。

## 7. 验证与继续工作

以下是源码验证，不需要为了此次纯文档提交重跑全部测试。Windows pytest 使用唯一临时目录，
旧 pytest-current 清理错误不能算测试通过；私有仓库测试须显式指定本次公共工作树。

```powershell
.venv/Scripts/ruff.exe check ironsbot tests
.venv/Scripts/basedpyright.exe
$testRoot = Join-Path $env:TEMP ('ironsbot-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests -q --basetemp $testRoot
.venv/Scripts/python.exe -m compileall -q ironsbot
git diff --check
```

私有扩展联合验证设置 `IRONSBOT_PUBLIC_ROOT` 为公共 V5 根目录；不要误测旁边的 main。
seerapi 有代码变化时在其自身环境测试和构建；公共数据库 schema 变化须先发布数据与模型，
不能让旧生产 main 无意消费不兼容版本。

### 可直接交给下一位 AI 的 Prompt

```text
继续 IronsBot 多仓库重构，先阅读 docs/refactor-handoff.md、ARCHITECTURE.md、
docs/engineering-workflow.md 和当前 QQ Official live acceptance spec。
用户暂停了前一个会话；不要假定历史测试进程仍活着。
核实工作树、远端和 HEAD，保留所有既存未提交内容，尤其 private 的 uv.lock。
公共工作分支 codex/multiplatform-architecture-v5，推送私有 qq-official-preview，
不覆盖公开 main。main 有更新时先 fetch/比较，说明影响后按授权范围整合。

当前进度 7/8，17/17 main 跟进是源码证据，不等于平台上线。
首先恢复或找到获授权的 Docker 运行环境，用交接文档里的精确 digest 完成真实矩阵。
源码 READY、CI 构建和 handler 返回均不能代替候选容器及实际消息送达。
凭据只经安全环境注入，不从旧聊天复制进文件或输出，不要求已经弃用的 Token。
NapCat 仅可选增强：observer 只隔离读写，不是已完成的 QQ/OpenID 映射。
不能猜身份，不能把双端协作变成官方独立发布的必要条件。

业务只复用通用 command/service/repository/reply 接口；不新建补丁入口、双读兼容、
运行时 SWF 转换或图片资源包。遵守 800 行与镜像体积门禁，按职责而非机械拆文件。
每个实际变更先写/更新 spec，再做回归与分功能提交；数据模型变化注意三仓发布顺序。
显示总任务、当前阶段、小任务的已验证进度及有依据的 ETA；阻塞时间不编估算。
同一阻塞没有新证据就停止无效轮询，说明需要的外部变化。
不要关闭 Phase 7 或宣称全目标完成，直到逐项要求具有同一候选的真实证据。
```
