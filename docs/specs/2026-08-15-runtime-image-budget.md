# 运行镜像体积预算与构建上下文

Status: `implementing`

Contract: `target`

Owner: `Dockerfile` runtime stage and release workflow

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#engineering-principles)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

主线持续增加功能时，镜像可能因直接复制仓库内容、构建工具残留或运行时依赖膨胀而
逐渐增大。当前工作环境没有可用 Docker daemon，不能伪造实际 image-size 结果。

## Goal

运行镜像只包含应用、运行依赖、字体和启动脚本；本地虚拟环境、测试缓存、Codex 工作
目录和构建工具不进入 build context 或最终镜像。每次新增大型运行依赖前，必须给出
功能归属和实际镜像层测量。

## Non-Goals

- 不删除 HTML 渲染核心、Pillow、SQLAlchemy、二维码、HTTP 缓存或 SVG 光栅化依赖，
  它们均有当前运行调用。
- 不在没有 Docker daemon 时声称镜像减少了多少 MiB。

## Ownership And Reuse

- Semantic owner: Docker runtime stage owns最终镜像内容；`.dockerignore` owns build context。
- Reused contracts: 多阶段 wheels 安装与 `--no-cache-dir --no-compile`。
- New interface: 无。该工作只收紧既有构建边界。

## User And Data Contract

- Inputs: Docker build context、`pyproject.toml`、`uv.lock`。
- Outputs: 相同行为的容器镜像，减少上传到 Docker daemon 的无关本地文件。
- Persistence: 无。
- Compatibility: 不改变 `docker-entrypoint.sh`、配置挂载或运行命令。

## Design

1. 最终 stage 继续只复制 `ironsbot/`、启动脚本、版本和示例配置。
2. `.dockerignore` 排除虚拟环境、AI 工作目录、字节码和测试/覆盖缓存。
3. 静态测试保护“不复制整个仓库”“不保留 Python 打包工具”和关键忽略项。
4. 有 Docker daemon 的发布环境再记录 `docker image inspect` 的真实体积，并对比前一
   个发布 digest；没有测量不得声称压缩百分比。
5. 2026-09-05 审计确认：`COPY --from=requirements_stage /wheel /wheel` 在最终镜像中
   生成持有全部安装包的独立层；后续 `rm -rf /wheel` 只隐藏文件，不能删除该层字节。
   安装改用 BuildKit 的只读阶段挂载，安装完成后只保留 site-packages，不再生成
   wheelhouse COPY 层。复用现有 wheels 构建，依赖和字体不删减。
6. 依赖导出显式使用 `--frozen --no-dev`，不得在构建中重新解析锁文件或带入开发工具。
7. 发布后的测量使用 `build-push-action` 返回的 digest，而不是可能变化的标签；
   保存 image inspect、逐层 history 到构建附件，并在摘要中列出真实体积。
   未发布或未测量时保持本 Spec 未完成。
8. 发布候选在仓库登录后、正式 push 前拉取当前 `latest`，按同一 Docker 引擎报告的
   镜像尺寸执行相对增长门。GHCR 基线由当前 `github.repository` 推导，不写死 fork
   所有者。默认单次最多增长 8192 KiB；基线 digest、候选大小和差值始终上传为
   独立附件。基线不可读取时发布失败，不能静默绕过比较。

BuildKit 挂载使用 [Docker 官方 RUN --mount 契约](https://docs.docker.com/reference/dockerfile/#run---mounttypebind)。
源码构建要求 BuildKit；当前 GitHub workflow 已配置 Buildx。预构建镜像部署方式不变。

## Acceptance Tests

- [x] 最终 Docker stage 不使用 `COPY . /app/`。
- [x] pip、setuptools、wheel 在最终安装层清理。
- [x] `.venv`、`.codex`、Python 缓存与 pytest 缓存不进入 build context。
- [x] 安装包只在 RUN 挂载中可见，最终阶段没有复制 wheelhouse 的指令（静态验收）。
- [x] 冻结运行依赖导出；CI 的 digest 测量和层信息附件已实现并经模拟命令验证。
- [x] 候选镜像在发布前与现有 `latest` 比较，超出 8192 KiB 时停止发布并保留证据。
- [x] 在 Linux/amd64 Docker 引擎真实构建候选，执行离线启动、字体、依赖导入、
  字节码排除和三个目录预算检查。
- [ ] 发布环境记录一次实际镜像层和总尺寸测量。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 审计运行依赖和 Docker 多阶段构建 | `uv export --no-dev`, `uv tree`, source search | 顶层运行依赖均有调用；HTML 渲染核心约 16 MiB，不能作为冗余删除。 |
| 2026-08-15 | 收紧 Docker build context | Docker static test | 使用项目专用忽略规则；本地 `.venv`、Codex、数据、文档、测试、构建脚本和缓存已排除，仍待真实 daemon 测量。 |
| 2026-08-15 | 运行依赖复核 | `uv export --no-dev`、`uv tree --no-dev --show-sizes`、Docker 静态测试（12 passed） | 约 109 MiB Node、52 MiB BasedPyright、pytest 与 virtualenv 均只在开发依赖组，不会导出到运行镜像；HTML 渲染、Pillow 和 SVG 光栅化均有运行调用。工作站 Docker daemon 不可用，仍待发布环境记录实际镜像尺寸。 |
| 2026-09-05 | 删除运行层 wheelhouse COPY，改为 BuildKit 只读挂载；冻结运行依赖导出 | Docker preflight 与发布 workflow 测试 16 passed；Ruff、测试模块 BasedPyright 与 diff 检查通过 | 实际执行 Bash 测量脚本，Docker 使用模拟函数；覆盖多标签、带端口仓库、缺失 digest 和附件生成。不是实际容器构建验收。 |
| 2026-09-05 | 本地 main 和构建环境复核 | `git show main:Dockerfile`、冻结依赖导出、`docker version` | main `f19c7089` 仍 COPY wheelhouse、COPY 全仓库，且导出未显式排除 dev。V5 已按白名单复制应用并排除 dev，本轮补齐 wheelhouse 层问题。本机 Docker engine pipe 仍不存在，不报告 MiB 减少值，实际构建与 digest 测量仍待完成。 |
| 2026-09-12 | 只读审计 Docker Hub `latest` 的 linux/amd64 manifest 与 config history | Registry digest `sha256:9aee18d5...`，10 层合计 405.51 MiB（压缩传输大小） | 当前远端仍由 main 旧 Dockerfile 构建：wheelhouse COPY 134.36 MiB、安装后删除 wheel 的层 153.02 MiB、全仓 `COPY .` 41.38 MiB。V5 已删除独立 wheelhouse 层并改为运行文件白名单，但尚未发布，因此不能声称新镜像的实际大小或节省比例。 |
| 2026-09-13 | 增加候选相对增长门 | Docker 发布、启动预检与结构边界测试 39 项 | 候选相对当前 fork 的 GHCR `latest` 最多增长 8192 KiB；缩小、零增长、边界值、超限、基线不可读及 fork 仓库推导均经验证，真实大小仍等首个 Linux 候选任务。 |
| 2026-09-13 | 本机真实 Linux/amd64 候选构建 | Docker Desktop Engine 29.5.2；commit `93bd3aac21e8`；离线 entrypoint smoke、字体解析、核心导入、目录 `du`、image inspect 与线上 digest 对比 | 候选 image ID `sha256:7ffd8c98...`，Docker 报告 98,861,824 bytes（94.28 MiB）；`/app` 4220 KiB、site-packages 104644 KiB、fonts 19452 KiB，均通过预算。线上 `latest` digest `sha256:4677ca61...` 为 425,224,471 bytes（405.53 MiB），同一引擎下候选少 326,362,647 bytes（311.24 MiB）。尚未 push 或生成 GitHub Actions 发布附件。 |
| 2026-09-13 | 移除未使用的 Uvicorn standard extras | 锁文件依赖边界测试、完整宿主进程启动与正常关闭 | 入口固定使用 `asyncio`、`h11`、`websockets-sansio`；锁文件移除 `httptools`、`uvloop`、`watchfiles`。Docker 引擎随后不可用，精确 Linux 镜像差值留给发布候选任务测量。 |
| 2026-09-13 | 修复嵌套字节码进入构建上下文 | 首次真实候选 `/app` 9384 KiB；递归忽略规则后重建、容器内 `find` 与 smoke | 根级 `.dockerignore` 模式没有排除嵌套 `__pycache__`；改为 `**/__pycache__/` 与 `**/*.py[cod]` 后 `/app` 降至 4220 KiB，减少 5164 KiB，容器内无 `.pyc`。同时修复 Dockerfile 旧式 `ENV` 警告。 |

## Progress

```text
Program  [███████░] 7/8 verified phases; real platform acceptance remains
Phase    [█████████░] local Linux candidate verified; published CI artifact remains
Current  [██████████] bytecode exclusion, smoke, budgets and baseline comparison verified
```
