# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping

from nonebot.log import logger

from ironsbot.config.models.runtime import RemoteBuildConfig, RemoteBuildStepConfig
from ironsbot.integrations.db_sync.github_actions import WorkflowRunResult

TriggerWorkflowFn = Callable[
    [RemoteBuildStepConfig],
    Awaitable[WorkflowRunResult],
]


def workflow_page(config: RemoteBuildConfig | RemoteBuildStepConfig) -> str:
    return (
        f"https://github.com/{config.repository}/actions/workflows/"
        f"{config.workflow_id}"
    )


def remote_build_failure(
    *,
    config: RemoteBuildConfig | RemoteBuildStepConfig,
    message: str,
) -> WorkflowRunResult:
    return WorkflowRunResult(
        ok=False,
        status="error",
        conclusion=None,
        html_url=(
            workflow_page(config)
            if config.repository and config.workflow_id
            else ""
        ),
        message=message,
    )


def format_exception_message(error: Exception) -> str:
    text = str(error).strip()
    if text:
        return f"{type(error).__name__}: {text}"
    return type(error).__name__


def configured_remote_build_steps(
    config: RemoteBuildConfig,
) -> list[RemoteBuildStepConfig]:
    return config.build_steps()


async def run_remote_build(
    *,
    name: str,
    config: RemoteBuildConfig | None,
    token: str,
    results: MutableMapping[str, WorkflowRunResult],
    trigger_workflow: TriggerWorkflowFn,
) -> bool:
    if config is None or not config.enabled:
        return True

    steps = configured_remote_build_steps(config)
    if not steps:
        results[name] = remote_build_failure(
            config=config,
            message="远程构建配置缺少 steps 或 repository/workflow_id",
        )
        logger.warning(f"数据库 '{name}' 远程构建配置缺少可执行 workflow")
        return False

    if not token:
        results[name] = remote_build_failure(
            config=config,
            message="缺少 GITHUB_WORKFLOW_TOKEN，未触发远程构建",
        )
        logger.warning(
            f"数据库 '{name}' 远程构建已启用，但未配置 GITHUB_WORKFLOW_TOKEN"
        )
        return False

    for step_index, step in enumerate(steps, start=1):
        if not step.repository or not step.workflow_id:
            results[name] = remote_build_failure(
                config=step,
                message=(
                    f"远程构建步骤 {step.display_name} "
                    "缺少 repository 或 workflow_id"
                ),
            )
            logger.warning(
                f"数据库 '{name}' 远程构建步骤配置不完整: {step.display_name}"
            )
            return False

        logger.info(
            f"开始触发数据库 '{name}' 远程构建步骤 "
            f"{step_index}/{len(steps)}: {step.display_name} "
            f"({step.repository}/{step.workflow_id}@{step.ref})"
        )
        try:
            result = await trigger_workflow(step)
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).error(
                f"数据库 '{name}' 远程构建步骤请求失败: {step.display_name}"
            )
            result = remote_build_failure(
                config=step,
                message=f"{step.display_name}: {format_exception_message(e)}",
            )

        results[name] = result
        if result.ok:
            logger.info(
                f"数据库 '{name}' 远程构建步骤成功: "
                f"{step.display_name}; Actions: {result.html_url}"
            )
            continue

        logger.warning(
            f"数据库 '{name}' 远程构建步骤失败: "
            f"{step.display_name}; {result.message}; Actions: {result.html_url}"
        )
        if not result.message.startswith(step.display_name):
            results[name] = WorkflowRunResult(
                ok=result.ok,
                status=result.status,
                conclusion=result.conclusion,
                html_url=result.html_url,
                message=f"{step.display_name}: {result.message}",
            )
        return False

    logger.info(f"数据库 '{name}' 远程构建流水线成功，共 {len(steps)} 步")
    return True


__all__ = [
    "configured_remote_build_steps",
    "format_exception_message",
    "remote_build_failure",
    "run_remote_build",
    "workflow_page",
]
