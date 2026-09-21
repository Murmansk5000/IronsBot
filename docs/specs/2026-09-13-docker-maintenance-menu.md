# Docker 维护菜单收口

Status: `implemented`

Contract: `target`

Owner: `services.operations.docker_update`

## Goal

将“只重启”和“检查、更新镜像后重启”定义为平台无关的维护动作。命令适配器只负责
打开菜单、传入选择并发送 service 返回的结果。

## Contract

- `/重启机器人`、`/机器人重启`、`/更新镜像`、`/更新Docker` 和 `/更新docker`
  打开同一维护菜单。
- `1` 只重启，不访问镜像仓库。
- `2` 检查镜像；有更新时启动 Watchtower 交接，无更新时重启当前容器。
- `/检查更新镜像` 与 `/检查镜像更新` 保持只读。
- 删除 `check_on_restart`。不保留旧配置或旧 service 方法的兼容读取。
- 新容器确认使用目标镜像后，按交接记录中的精确旧镜像 ID 执行非强制删除。
- 启动检查确认当前镜像已是最新时，清理同一公开 IronsBot 仓库中未被引用的历史
  镜像；无标签镜像必须具有与当前镜像相同的 OCI 来源标签。
- Docker 返回镜像仍被容器引用时保留镜像；不得删除引用它的容器，也不得执行全局
  `image prune`。
- 不自动清理私有扩展包、Watchtower、Python 或其他仓库镜像。
- 私有扩展镜像拉取并成功读取归档后，同样只清理本次被替换且未被引用的旧镜像。

## Boundaries

- 维护选项、解析和执行计划由 operations service 所有。
- OneBot 只拥有临时数字会话和最终发送。
- 超级管理员判定继续沿用当前 OneBot 权限；QQ 号映射及目标平台管理员身份按平台能力
  延期到最终适配阶段，不在本切片中硬编码。

## Verification

- Docker service、配置、命令目录和插件注册专项测试。
- Ruff、BasedPyright、compileall 与 `git diff --check`。
- Watchtower 的真实交接仍需 Linux Docker 环境验收。
