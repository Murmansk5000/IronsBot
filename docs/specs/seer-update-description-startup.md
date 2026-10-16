# 启动更新说明快照修复

状态：completed（实现与离线验收完成；生产发布另有监督验收记录）。
契约：baseline；日期：2026-11-16。

## 根因与边界

生产SeerAPI文件具有api_metadata与seerapi_metadata，schema契约为2。
异常调用链是DatabaseSync._describe → update_description：同步前读取空内存占位库，
尚未载入本地完整发布数据。此前修复覆盖version/_publication，未覆盖该新增读取入口。
这不是生产数据库再次缺表，也不是原修复因历史整理丢失。

## 实施契约

- 更新说明在一个现有快照租约内读取；未注册或空占位库返回DataVersion("unknown")。
- 占位状态不查询api_metadata或peak_season，交由同步器沿用指纹降级，不记录异常。
- 已加载版本号、生成时间与赛季来自同一engine；并发换版不混合两代数据。
- 真正损坏或不合契约的发布仍明确失败，不建空表、不吞SQL异常、不伪造成功通知。
- 不改变公开接口、SeerAPI、TOML、通知权限或生产数据库，不新增迁移。

## 验收与发布

覆盖空占位、未注册、首次同步、匹配本地缓存、后续更新、损坏发布及并发换版。
隔离运行定向和完整pytest、Ruff、BasedPyright、compileall、仓库静态及差异检查。
仅使用预留模块的已提交测试副本；保留当前.gitignore等并行修改。
独立提交并累计原始归档后推送main，等待精确SHA镜像发布，再仅监督更新ironsbot。
验证启动、11个官方账号、60秒稳定期及缺表调用栈消失，失败恢复旧容器。
不发送生产测试消息，不操作其他应用容器。

## 实际离线验收

- 修改前红测4项失败、2项对照通过，复现空库告警和换版混用。
- 最终专项60项通过；完整pytest为7145项通过、11项跳过。
- Ruff、BasedPyright、compileall、仓库静态及差异检查全部通过。
- 覆盖首次下载、匹配本地缓存、持久化成功后的通知、重复同步不重复通知，
  并确认损坏发布拒绝换入、保留旧发布、不能报成功。
- 生产只读证据确认两个元数据表均存在，api_metadata有1行，schema契约为2；
  原告警调用栈终点是update_description，不是发布文件校验。
- 各轮日志、修复前证据及后续源码/归档/镜像/监督部署记录保存在
  `E:/IronsBot-history-validation/seer-update-description-20261116`。
- 未读取或修改预留工作副本，未更改生产配置或手工修改数据库。
