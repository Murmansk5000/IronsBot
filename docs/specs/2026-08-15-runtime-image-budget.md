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

BuildKit 挂载使用 [Docker 官方 RUN --mount 契约](https://docs.docker.com/reference/dockerfile/#run---mounttypebind)。
源码构建要求 BuildKit；当前 GitHub workflow 已配置 Buildx。预构建镜像部署方式不变。

## Acceptance Tests

- [x] 最终 Docker stage 不使用 `COPY . /app/`。
- [x] pip、setuptools、wheel 在最终安装层清理。
- [x] `.venv`、`.codex`、Python 缓存与 pytest 缓存不进入 build context。
- [x] 安装包只在 RUN 挂载中可见，最终阶段没有复制 wheelhouse 的指令（静态验收）。
- [x] 冻结运行依赖导出；CI 的 digest 测量和层信息附件已实现并经模拟命令验证。
- [ ] 发布环境记录一次实际镜像层和总尺寸测量。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 审计运行依赖和 Docker 多阶段构建 | `uv export --no-dev`, `uv tree`, source search | 顶层运行依赖均有调用；HTML 渲染核心约 16 MiB，不能作为冗余删除。 |
| 2026-08-15 | 收紧 Docker build context | Docker static test | 使用项目专用忽略规则；本地 `.venv`、Codex、数据、文档、测试、构建脚本和缓存已排除，仍待真实 daemon 测量。 |
| 2026-08-15 | 运行依赖复核 | `uv export --no-dev`、`uv tree --no-dev --show-sizes`、Docker 静态测试（12 passed） | 约 109 MiB Node、52 MiB BasedPyright、pytest 与 virtualenv 均只在开发依赖组，不会导出到运行镜像；HTML 渲染、Pillow 和 SVG 光栅化均有运行调用。工作站 Docker daemon 不可用，仍待发布环境记录实际镜像尺寸。 |
| 2026-09-05 | 删除运行层 wheelhouse COPY，改为 BuildKit 只读挂载；冻结运行依赖导出 | Docker preflight 与发布 workflow 测试 16 passed；Ruff、测试模块 BasedPyright 与 diff 检查通过 | 实际执行 Bash 测量脚本，Docker 使用模拟函数；覆盖多标签、带端口仓库、缺失 digest 和附件生成。不是实际容器构建验收。 |
| 2026-09-05 | 本地 main 和构建环境复核 | `git show main:Dockerfile`、冻结依赖导出、`docker version` | main `f19c7089` 仍 COPY wheelhouse、COPY 全仓库，且导出未显式排除 dev。V5 已按白名单复制应用并排除 dev，本轮补齐 wheelhouse 层问题。本机 Docker engine pipe 仍不存在，不报告 MiB 减少值，实际构建与 digest 测量仍待完成。 |

## Progress

```text
Program  [███░░░░░░░]  verified phases: 3/8; this static boundary is complete, real image measurement remains
Phase    [██████████] static build context protection verified; image-size acceptance remains open
Current  [██████████] wheelhouse and measurement code verified; actual image build and size pending
```
