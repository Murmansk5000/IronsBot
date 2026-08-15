# 运行镜像体积预算与构建上下文

Status: `verified`

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

## Acceptance Tests

- [x] 最终 Docker stage 不使用 `COPY . /app/`。
- [x] pip、setuptools、wheel 在最终安装层清理。
- [x] `.venv`、`.codex`、Python 缓存与 pytest 缓存不进入 build context。
- [ ] 发布环境记录一次实际镜像层和总尺寸测量。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 审计运行依赖和 Docker 多阶段构建 | `uv export --no-dev`, `uv tree`, source search | 顶层运行依赖均有调用；HTML 渲染核心约 16 MiB，不能作为冗余删除。 |
| 2026-08-15 | 收紧 Docker build context | Docker static test | 使用项目专用忽略规则；本地 `.venv`、Codex、数据、文档、测试、构建脚本和缓存已排除，仍待真实 daemon 测量。 |
| 2026-08-15 | 运行依赖复核 | `uv export --no-dev`、`uv tree --no-dev --show-sizes`、Docker 静态测试（12 passed） | 约 109 MiB Node、52 MiB BasedPyright、pytest 与 virtualenv 均只在开发依赖组，不会导出到运行镜像；HTML 渲染、Pillow 和 SVG 光栅化均有运行调用。工作站 Docker daemon 不可用，仍待发布环境记录实际镜像尺寸。 |

## Progress

```text
Program  [███░░░░░░░]  verified phases: 3/8; this static boundary is complete, real image measurement remains
Phase    [██████████] 100% current: build context protection
Current  [██████████] 100% next: measure after Docker daemon becomes available
```
