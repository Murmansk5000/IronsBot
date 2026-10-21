# 管理口令统一群聊开关

Status: implementation_complete; historical placement awaiting confirmation (2026-11-21).
Contract: baseline extension; no role/feature/cooldown/target authorization bypass.

## Behavior

仅提供 `[bot] admin_commands_in_groups = true`，默认允许超管在群聊使用管理口令。
设为false仅关闭群聊管理入口；超管私聊保持可用。不提供both/group/private选项。
普通查询、群管理员功能、个人TD、AI私聊和超管专属资料查询不受影响。
契约显式标记management，必须是超管权限；公共目录统一应用群聊开关，
帮助、匹配、菜单及执行前复查使用同一有效契约，不维护另一份指令ID清单。

## History and Verification

先提交/追加干净原始归档，再验证干净bundle、在隔离检出中整理历史。
原拟将配置/契约归入86a7d8a655；该节点的目录仅参与帮助与匹配说明，
旧OneBot执行未使用目录授权。不能仅回填目录便声称历史节点行为完整。
历史折叠位置待确认；如保留原节点，需要同步适配当时执行授权。
后续管理口令必须在其实际引入节点接入，不能提前引用未来接口。
保留27个上游原SHA、作者日期、合并结构、其他未提交修改及预留文件。
覆盖双平台true/false、私聊不受影响、超管/群管理员/普通成员、黑名单、
功能关闭、旧菜单及执行复查。执行历史检查及最终完整质量检查。

## Boundaries

不推送公共main、不构建/部署，不修改生产TOML、数据库或容器。
本轮精灵形态相关并行修改不读取/编辑/暂存，不纳入本功能。

## Evidence

2026-11-21：仅在干净提交及本功能文件组成的隔离检出中验证，未纳入并行精灵改动。
完整pytest：7472通过、11跳过；BasedPyright：0错误；compileall、仓库静态及差异检查通过。
全量检查发现测试布尔参数需为仅关键字参数，修正后Ruff通过；该修正不改变业务代码。
双平台专项覆盖群聊开关、私聊保持可用、超管/群管理员/普通成员及黑名单。
历史改写、公共推送和生产部署尚未执行；不能将本次隔离结果当作历史节点验收。
