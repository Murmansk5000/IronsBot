# 苏摩详情可选私有图片

Status: `in_progress` (native isolated prototype verified; repository acceptance pending)
Contract: `baseline` extension
Owner: public player details/render coordinator; optional private avatar provider

## Scope And Licensing

选择常用苏摩后显示所选实例的透明PNG，保留中文详情与0返回；不添加菜单、权限、
游戏请求或未验证外观特效。用户已确认六张实验样图正确；这不是所有客户端版本、
成长阶段或动画的通用兼容证明。

2026-11-24用户确认完全非商业用途，允许wang606转换器的PolyForm Noncommercial
1.0.0。private不是许可豁免，不改标GPL，不将该工具放入公共镜像。私有运行镜像
单独保留原许可、署名和版本清单。未来商业使用或向其他主体分发须重新核对条件。
游戏素材权利与工具许可分开判断，游戏原包、转换JSON、纹理和实测图片不提交归档。

## Public Contract And Ownership

`ironsbot.extensions.somua_avatar`提供不可变九部件及固定输出请求：normal第0秒、
768x768透明PNG。不给提供者平台事件、操作者、凭据、ORM或完整应用运行时。
现行ExtensionServices增加可选somua_avatar能力，重复提供者注册明确拒绝。

提供者prepare返回异步资源租约，持有resource_version、renderer_fingerprint、
degraded、notice和render回调。准备受公共execute总期限限制；降级在读取缓存前
确定，缓存命中仍保留notice。资源未就绪由生命周期任务准备，前台返回真实文字。
没有安装可选提供者时继续原有文字功能；已注册但缺少工具时明确图片不可用。

公共RenderCoordinator.render_backend与HTML使用同一信号量、期限、阶段和取消
契约，不在private另建业务队列。只有完整图片经公共延迟发布机制写最终缓存，键
覆盖九部件、资源版本、渲染器、输出规格。private只管理素材与转换缓存。
租约覆盖缓存读与渲染，旧资源不能在使用中删除。失败、取消、迟到结果不写成功缓存。

原始详情缓存与实时查询使用同一可选图片接线，不增加45969请求，不更改实际取得
时间或query_work。图片失败不丢中文与导航，不重新执行游戏操作或重复扣额。
真正渲染错误接入同一脱敏管理诊断；预期资源未就绪不升级为管理异常。

## Private Delivery

private main/details实现同一贡献项，保留两分支阵容差异。原Alpine扩展文件包和
16MiB/路径/链接安全限制不变。另加可选Debian/glibc runtime构建目标，基于明确
配对公共镜像在构建期备齐CLI、Node及运行库，最终仍只运行一个ironsbot容器。
运行时不安装工具；下载资源与断网转换分离，转换及原生出图进程不能访问凭据或外网。
完整校验候选资源后原子发布，同版本单飞；失败不发布半成品。旧版只有完整覆盖
请求部件才可降级使用，并显式标注、不写完整图片缓存。

## Verification And Delivery

主项目覆盖无提供者、重复注册、类型边界、缓存/实时、TTL不续期、无额外请求、
降级命中与notice、版本隔离、共享队列、超时、取消、错误通知失败及文字保底。
双平台回归原菜单、返回、权限及实际操作者校验，失败发送不重做查询。

私有组件覆盖六图基线、缺失皮肤/纹理、损坏资源、转换/原生后端失败、单飞、
原子换版与租约清理。必须在非生产Linux验证ABI、WebGL2和取消清理，不能把
Windows/Codex/WSL实验路径当正式容器支持；不可执行的验收如实列为缺口。

两仓库定向及完整测试、Ruff、BasedPyright、compileall、架构和差异检查以实际
记录为准；预留工作文件仅在隔离检出使用已授权的提交版本。最初源码阶段不折叠、
不推送开发分支；本轮按新的用户授权，先分仓独立提交并追加干净原始归档，再验证
干净bundle、按功能折叠并受保护推送。私有runtime增加仅构建/离线验收的CI，不发布
含非商业工具的runtime镜像，不部署或修改生产。

### Initial Source Verification (2026-11-24)

公共隔离完整pytest为7557通过、11跳过；最后的组装行长整理后，76项图片、
双平台菜单、插件组装及架构回归再次通过。Ruff、BasedPyright（0错误）、
compileall、仓库静态及差异检查通过。预留文件只在隔离检出使用已提交版本。
private main为88通过、1跳过；details为126通过、1跳过，含共同图片提供者、
资源单飞/恢复/完整性、未知皮肤、浏览器失败/取消及注册清单验证。
固定Bone-2D静态bundle实际构建成功；冻结4.0.64转换结果的613个皮肤及骨骼、
槽位、附件和atlas引用通过私有发布前检查。此检查不等同于重新完成六图视觉验收。

最初的浏览器方案在隔离WSL BuildKit中尝试，Docker Hub的dockerfile前端拉取连接超时，
未进入编译阶段。该临时构建器已停止；未启动Docker Desktop或操作生产容器。
该阶段没有完成ABI、成品容器内WebGL2、实际转换/出图、默认安全策略下bubblewrap及
进程清理验收；这不是后续原生方案的验收结果。公开代码不含转换器，配对提交不等同于
已有配对镜像摘要。

### Native Single-container Design (2026-11-24)

借鉴spine-exporter的Node原生出图方式，不引入其Spine 3.8运行库。保留固定Bone-2D和
非商业转换器，使用Node 24.22.3、gl 9.0.0-rc.10及软件Vulkan；不需要浏览器或渲染服务。
公共接口、队列、超时、告警、最终图片缓存及中文详情/导航保持原有所有权。

Minijail固定c46d08600b8b6548809d37be1964396efde1c3ac。每个任务使用最小根目录、
独立UID/GID、空capabilities、no_new_privs及子进程seccomp白名单；不使用用户或挂载
命名空间，不添加容器能力或放宽Docker默认seccomp。固定工具归root且不可被任务修改，
输入只读，仅任务输出可写；临时路径也位于输出目录内。关闭继承描述符，禁止网络、
抽象Unix socket、进程内存访问及脱离受控进程组。取消先终止并回收子进程，再清理任务。
缺少隔离能力或安全探针失败时保持文字保底，不尝试未隔离执行。

原生gl需要匹配的GCC运行库及实际可加载的Vulkan loader。该预发布版固定返回WebGL 1
版本字符串，原样记录，不伪造为WebGL2；用GLSL ES 3.00编译、VAO、真实纹理绘制及
像素读回验证所需能力。更新运行时清单指纹，以隔离旧浏览器后端的最终图片缓存。

### Native Prototype Evidence (2026-11-24)

仓库外WSL Linux容器中，使用Docker默认seccomp、无新增capabilities且断网执行：

- 同一工具镜像内完成骨架转换和Unity素材提取；转换JSON、骨架、图集与冻结基线一致，
  共70页纹理。严格输出权限在ext4验证，不能用不保留Linux模式的Windows挂载替代。
- 六组已确认组合均生成768x768透明PNG，无空图或边缘裁切；Minijail内外的原生输出
  像素完全一致。与浏览器基线的抗锯齿差异另行记录，不冒称PNG字节完全相同。
- 16项探针及双任务隔离通过，覆盖UID/GID、capabilities、环境、凭据路径、输入只读、
  继承描述符、网络、抽象socket、ptrace、进程内存及会话逃逸；取消和超时后子进程已回收。
- seccomp采用整进程终止模式，违规不会只终止主线程而遗留工作线程。未知部件、全空
  外观和非法输出规格明确拒绝，不返回默认样本。

上述证据仅证明隔离原型。仓库接线、最终成品镜像、三仓完整质量检查、历史折叠、配对
发布及累计归档仍须分别完成；本次没有部署生产容器，也不修改生产配置或数据库。

### Native Source Acceptance And Image Gate (2026-11-24)

原生仓库接线已完成：private main/details 使用相同的规范化 Git blob，移除旧浏览器
及 bubblewrap 接线。取消回归发现并修复了清理期间取消可能返回已完成图片的窗口，
现在回滚已发布输出并继续传播取消。公共图片接口与业务执行路径未改变。

使用隔离检出和配对锁定依赖：公共 Python 3.11 完整测试为7557通过、11跳过；
private main为84通过、1跳过，details为122通过、1跳过。三者Ruff及BasedPyright
通过（0错误），编译检查通过。首次Python 3.12测试出现一项READY事件时序失败及
两项SQLite默认日期适配器弃用告警；未修改无关业务或关闭告警，改用CI对应的3.11
环境完成上述全量验证。不同环境和阶段的结果不得合并计算。

最终仓库Dockerfile构建尚未完成。三次隔离构建分别遇到GitHub TLS/early EOF、
PyPI索引响应截断及GitHub fetch断开；仍启用TLS验证，未调整生产网络。
尚未在最终候选镜像内执行六图和安全烟测，原型结果不能替代该门槛。因此本轮未
生成修复提交、追加归档、制作历史bundle、折叠历史或推送替换版本，也未部署。

### Authorized Real-machine Trial (2026-11-24)

用户随后授权先独立提交、追加原始归档并正常快进发布，再构建私有runtime，仅更新
Unraid的ironsbot实机试运行；完整六图验收和历史折叠暂缓。镜像构建、完整性校验、
隔离安全探针及自动检查仍是部署前置条件，不发布含非商业转换器的公共runtime镜像。
WSL本地构建的镜像以校验过的归档传入Unraid；保留原镜像与容器回退依据，不清理旧版本。
隔离失败保持中文详情，不尝试无隔离执行；启动或连接失败回退，只有图片失败时保留
正常文字服务并记录原因。生产TOML、数据库、其他容器及网络配置不在修改范围。

用户新提供的187618174三张常用苏摩图片作为试运行视觉基线，只保存在仓库外。
部署后通过实际公共查询与图片提供者核对三只的部件、层级、透明度及裁切，不主动
向生产会话发送测试消息；实时外观若有变化须与渲染错误区分。发布、构建与部署结果
必须另行记录，以上授权不代表这些步骤已经完成。
