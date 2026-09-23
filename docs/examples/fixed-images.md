# 固定图片口令配置

[fixed-images.toml](fixed-images.toml) 展示五个内置口令的完整配置形态。
这些口令及图片现在随程序默认启用，不需要把该片段复制进运行配置。
需要关闭或覆盖某个内置口令时，只需在现有 `[messaging.sendpic]` 后使用相同 ID；
例如关闭技能石：

```toml
[[messaging.sendpic.configs]]
id = "skill-stone"
enabled = false
```

原版资源位于 `ironsbot/integrations/assets/sendpic/`：

| 口令（包括别名） | 文件 |
| --- | --- |
| 学习力、学习力表、学习力表格 | 学习力表格.png |
| 巅峰姬 | 巅峰姬.png |
| 必先 | 必先.png |
| 技能石 | 技能石.png |
| 周年庆伪随机表、伪随机表 | 周年庆伪随机表.png |

`local_root` 只用于额外配置的 `backend = "local"` 图片，不影响内置图片。

这些图片已重新打包进运行镜像。变更 TOML 后重启应用以重新装配命令目录。
两端均需启用 `image`
Feature，官方账号还需具有媒体发送能力；具体准入遵循现有权限配置。
新增图片只需增加同结构配置和文件，不写平台专用 handler。

测试覆盖配置解析、八个口令的目录生成、五种内置资源的读取和平台中立图片结果。
