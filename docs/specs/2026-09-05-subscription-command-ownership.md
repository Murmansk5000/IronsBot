# 订阅命令的解析与目录收口

Status: `verified`

Contract: `target`

Owner: B站、战队资源、幸运橱窗领域命令服务

## Problem

B站推送模式、战队订阅和橱窗关注的实际解析器支持参数，目录却只有示例。
橱窗多个替代命令以 `A / B` 存在一个 examples 项，不能直接输入，也会被戳一戳
当作一条命令提示。战队快捷查询已由 TOML commands 控制，但目录仍写死“战队”。

## Design

- 在 core 提供无副作用的 parser-to-input-matcher 适配，None 表示未识别，其他
  返回值（含 0）表示识别；可按解析结果筛动作。复用到榜单和本次订阅命令，
  不引入第二份语法或配置。
- B站模式目录复用 parse_bili_push_mode_command，补全账号查询别名。权限仍为
  群管理者或私聊本人，账号/模式有效性仍由业务验证。
- 战队目录按现有 parse_team_resource_manage_command 的 add/remove/list 分类。
  query examples 来自当前 TOML commands。查看订阅列表按实际 handler 是只读普通
  权限；增删仍仅群管理者或私聊本人。无效参数的既有处理不改变。
  query commands 为空时目录和 matcher 均不注册快捷查询；功能关闭时两者均不注册。
- 橱窗精确词和变更参数解析从 OneBot 移到已有 lucky_skin_commands，目录与适配器
  共用；OneBot 仅做 feature 和 state 适配。每个 example 只存一个可输入的命令。
- 不改变数据库、登录确认、关注逻辑、推送、配额或网络请求。不增加运行依赖。
- 不保留旧签名回退，插件的本地绑定/菜单逻辑不在本项重写。

## Acceptance

- 三领域参数、别名、空参数与无效输入按实际 parser 认领；未启用功能不认领。
- 增删命令不向普通群成员开放；战队只读列表与真实 handler 权限一致。
- 普通私聊合法命令不被 AI 接管；无命令归属的聊天保持可用。
- 橱窗每个帮助示例可单独输入，list/add/remove/clear/reset 归属不混淆。
- 自定义战队 query commands 同时作用于帮助和认领。
- parser 适配对 None/0/过滤谓词有测试，不读取绑定或执行 IO。
- Ruff、BasedPyright、专项和完整公开 pytest、私有 pytest、compileall、diff。

## Evidence

- 原始认领回归：24 failed / 4 passed，覆盖实际私聊 AI 判定。
- 收口后的首批专项：101 passed。新增全部橱窗 example 对实际 OneBot rule 的
  逐条验证，以及自定义/空口令、禁用战队的目录与 matcher 安装校验。
- 最终公开全量 `uv run pytest -q --basetemp=.test-tmp/subscription-final`：
  2261 passed，111 条既有依赖告警（新增安装测试增加相同告警次数），1200.55 秒。
- 私有仓库指定当前 V5 为 IRONSBOT_PUBLIC_ROOT：26 passed。
- `uv run basedpyright ironsbot tests`：0 errors / warnings / notes，退出码 0。
  首次无路径检查扫描工作区耗时过长，虽打印 0 errors 但退出码 1，不计通过；
  以随后明确覆盖公开代码和测试目录的检查为验证证据。
- Ruff、compileall、git diff --check 通过。无新增依赖、配置、数据库或生产操作。
- 总进度保持 4/8。消息推送菜单入口仍标为 conversation，不属于本次三领域
  parser 收口范围；其目录/AI 认领及普通菜单输入边界须单独验收。
