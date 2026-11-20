# B站动态编辑对照重推

Status: completed implementation and verification (2026-11-20).
Public main is not published; production is not deployed by this work.

Contract: `baseline` extension

Owner: Bilibili revision observation, existing delivery ledger/FIFO and public render coordinator.

## Goal And Boundaries

全部已监控账号在原发布时间后24小时内检测编辑，仅发送变化对照。复用现有
`BiliPushTargets`、分类、TD、路由、发送和回执，不增加目标类型、配置或高频任务。
不修改生产，不补发历史，不改写历史；根预留文件及原有修改保留。

## Design

- 在历史覆盖前保存完整可读版本，忽略互动计数及图片CDN协议/主机/参数。
  版本序号允许A→B→A，重复观察当前版本不新增事件。真实动态ID不变，内部版本键独立。
- 版本及待投递事件同一SQLite事务；幂等转入既有账本后确认，不重置旧任务状态。
  升级以既有可信历史建立基线，首次完整在线观察只校准、不重推无法定时的旧编辑；
  已初始化版本的重启不重复校准，不丢弃待投递事件。
- 普通轮询按既有间隔最多复查10条、并发2、最久未检查优先；加强检查不额外复查。
  部分数据、接口及鉴权失败不推进内容版本。
- 文本红删绿增，数字整体；图片增删/换序/替换使用同范围新旧裁片，压缩噪声容忍，
  不可靠时完整对照。旧图缺失明确标注，不猜测。原图和文字不因另一部分变化而重发。
- 对照走现有RenderCoordinator，失败用真实文字摘要；正文图仍受正文TD限制。
  版本进入既有FIFO，保留四次/60秒重试与不确定阻断。每阶段复查现有权限和订阅。
- 版本与任务均不因编辑延长24小时；媒体登记复用既有事务和引用清理。
  发送或准备中的执行租约同时保护前驱版本，完成后仍按原有效期清理。

## Delivery Slices

| Slice | Acceptance | Status |
| --- | --- | --- |
| Version store | semantic identity, transactional outbox, idempotent baseline | verified |
| Comparison | public rendering, exact source evidence and truthful fallback | verified |
| Integration | polling, FIFO/recovery, TD, restart and full checks | verified |

## Validation

真实隔离样本1272396948553334785：文字未变，750×7598长图局部
“浩瀚星核×60→星际密令×60”。旧CDN返回404，首发冻结字节SHA校验通过。
样本在外部诊断目录，不进入Git。覆盖连续编辑、预算、24小时、失败及迁移，
两平台公共发送回归；执行pytest、Ruff、BasedPyright、compileall、静态及差异检查。

## Migration And Rollback

新增幂等版本/事件表，不修改既有成功回执。回退不得覆盖实时账本；旧代码不能接管
版本键任务，后续部署回退须保留支持该身份的投递代码，不能直接用旧镜像重放编辑任务。
媒体继续由既有delivery_media内容寻址管理，不在数据库存图片、不使用不可信旧值。

## Evidence

2026-11-20：版本存储独立隔离测试7通过；最终专项90通过、2跳过，覆盖双方平台
TD过滤、连续编辑FIFO、不确定阻断、登记后崩溃、保底重启及跨期素材保护。
真实公共litehtml后端生成1200×598局部对照图，保留“浩瀚星核×60”和“星际密令×60”
的同范围上下文；文字样图核对完整数字、箭头分隔和HTML转义。
样本及日志位于外部`bilibili-edits-20261120`诊断目录，不进入Git。
最终隔离完整pytest：7374通过、11跳过；Ruff、BasedPyright（零错误）、compileall、
仓库静态及差异检查通过。Ruff首次扫到了隔离pytest生成的夹具；将该批产物原样
移出源码目录后复查通过，未关闭规则，原失败日志保留。
早期一轮完整检查中，既有20ms期限用例出现failed/uncertain断言差异；最终串行
完整检查通过，该用例及生产期限均未修改。被替换候选的中止记录保留在外部日志。
恢复通知独立验证真实动态ID与编辑版本分开展示；不存在生产消息或部署验收。
