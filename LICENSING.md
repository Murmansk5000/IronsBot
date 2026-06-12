# 授权说明 / Licensing

本项目采用**多协议（multi-license）**结构。请在使用、修改或分发前阅读本说明。

## 概览

| 范围 | 协议 | 说明 |
| --- | --- | --- |
| 整机 / 组合作品（完整仓库、Docker 镜像、可运行的 bot） | **GPL-3.0-or-later** | 因包含下方 GPL 组件，整体作为"组合作品"对外分发时必须遵守 GPL-3.0。 |
| `ironsbot/custom_plugins/custom_get_seer_info/**` | **GPL-3.0-or-later** | 赛尔号查询插件适配层与仍在使用的 upstream-derived helper 边界。 |
| `ironsbot/services/seer/**` | **GPL-3.0-or-later** | 从赛尔号查询插件抽出的领域服务、渲染与纯计算逻辑。 |
| `ironsbot/plugins/seer/rank_help/**` | **GPL-3.0-or-later** | 榜单帮助入口，依赖 GPL Seer 榜单说明服务。 |
| `ironsbot/plugins/get_seer_info/templates/**` 与相邻 upstream 文档/许可证 | **GPL-3.0-or-later** | 保留的 upstream 渲染模板、图片资产与许可资料；旧 Python 插件代码已迁移或删除。 |
| `ironsbot/plugins/headless_seer/**` | **GPL-3.0-or-later** | 见 [ironsbot/plugins/headless_seer/LICENSE](ironsbot/plugins/headless_seer/LICENSE)，另见同目录 `NOTICE` |
| 其余全部代码（其他插件、`ironsbot/utils`、`bot.py`、`docker/` 等） | **MIT** | 见根目录 [LICENSE](LICENSE) |

GPL-3.0 全文见 [LICENSE.GPL-3.0](LICENSE.GPL-3.0)。

## 这意味着什么

- **单独复用非插件模块**：你可以单独提取以 MIT 标注的模块（例如 `ironsbot/plugins/seer_data`、`ironsbot/utils` 等），按 MIT 协议在你自己的项目中使用，无需承担 GPL 义务（可闭源、可商用）。
- **分发整机仍受 GPL 约束**：由于 Seer 查询、Seer 服务与 `headless_seer` 等 GPL 组件与 bot 在同一进程内紧密耦合，构成"组合作品"。当你分发**整个项目 / Docker 镜像 / 可运行的 bot** 时，整体必须按 GPL-3.0 分发（提供对应源码、保持 GPL 等）。MIT 标注**不会**解除整机的 GPL 义务。
- **依赖方向**：GPL 组件依赖（import）部分 MIT 模块，而 MIT 模块不依赖这些 GPL 组件，因此未列入 GPL 范围的 MIT 模块可独立提取使用。

## 文件级标注

每个源文件顶部带有 `SPDX-License-Identifier` 标识，用以明确该文件的协议归属：

- MIT 文件：`# SPDX-License-Identifier: MIT`
- GPL 文件：`# SPDX-License-Identifier: GPL-3.0-or-later`

## 第三方出处

`ironsbot/plugins/headless_seer` 中的 session 获取与登录数据包构建相关函数改写自
[oldml/saixiaoxi](https://github.com/oldml/saixiaoxi)（MIT, Copyright (c) 2025 Adai）。
详见 [ironsbot/plugins/headless_seer/NOTICE](ironsbot/plugins/headless_seer/NOTICE)。
