# 固定图片口令部署

[fixed-images.toml](fixed-images.toml) 是可选配置片段，不是完整运行配置，
也不会被应用自动加载。将其中五个配置项合入现有
`[[messaging.sendpic.configs]]`，并在已有 `[messaging.sendpic]` 设置
`local_root`。不要重复声明表或已有图片配置 ID。

原版资源位于 `ironsbot/integrations/assets/sendpic/`：

| 口令（包括别名） | 文件 |
| --- | --- |
| 学习力、学习力表、学习力表格 | 学习力表格.png |
| 巅峰姬 | 巅峰姬.png |
| 必先 | 必先.png |
| 技能石 | 技能石.png |
| 周年庆伪随机表、伪随机表 | 周年庆伪随机表.png |

部署时把这五张文件放到配置的图片根目录，保留文件名。
片段中的 `data/sendpic` 相对于进程工作目录；本机也可以改成绝对路径。
Docker/Unraid 的 `local_root` 应填写容器内路径，例如
`/app/data/sendpic`，不是 Unraid 主机路径。如果现有数据卷映射为
`/mnt/user/appdata/ironsbot/data:/app/data`，主机对应目录就是
`/mnt/user/appdata/ironsbot/data/sendpic`，不需要再加环境变量或端口。

这些图片仍为部署资源，不重新打包进运行镜像，不恢复旧 fixed/builtin
后端。变更 TOML 后重启应用以重新装配命令目录。两端均需启用 `image`
Feature，官方账号还需具有媒体发送能力；具体准入遵循现有权限配置。
新增图片只需增加同结构配置和文件，不写平台专用 handler。

测试覆盖配置解析、八个口令的目录生成、五种资源的读取和平台中立图片结果。
测试使用临时文件，不证明部署文件已安装，也不替代官方实际上传与发送验收。
