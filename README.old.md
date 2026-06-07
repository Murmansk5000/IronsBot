<div align="center">


# IronsBot
赛尔号信息查询机器人👊🤖🔥

[![Python](https://img.shields.io/badge/python->=3.10-blue.svg)](https://python.org) [![License](https://img.shields.io/badge/license-GPL--3.0%20%2F%20MIT-blue.svg)](LICENSING.md)
[![SeerAPI](https://img.shields.io/badge/SeerAPI-v104-blue.svg)](https://github.com/SeerAPI)
</div>

> 本项目原作是 [**@火火**] 开发的西塔伦Bot，谨以此项目向 [**@火火**] 致敬，感谢他为赛尔号玩家社区所做的贡献，愿火种永存。
> 
> 本项目继承了西塔伦Bot的数据查询功能，不包含配置投稿/推荐功能，这些功能请查看[这个链接（目前还没有）]()获取更多信息。
>
> 本项目中headless_seer插件的session获取与登录数据包构建函数来源于 [@oldml](https://github.com/oldml) 的项目 [saixiaoxi](https://github.com/oldml/saixiaoxi)，在此表示感谢。

## 部署
与西塔伦Bot不同，本项目不提供托管服务，用户需要自行部署。

硬性需求：
- 一台可运行操作系统并可以访问网络的计算机
- 一个QQ账号


### 在 Linux 上部署（推荐）

#### 前置要求

- [Docker Engine](https://docs.docker.com/engine/install/) 和 [Docker Compose](https://docs.docker.com/compose/install/)
- 一个 OneBot 实现端

我们使用[NapCat](https://github.com/NapNeko/NapCatQQ)作为OneBot实现端为例。
#### 1. 创建工作目录

```bash
mkdir -p ~/ironsbot && cd ~/ironsbot
```

#### 2. 创建 docker-compose.yml

创建 `docker-compose.yml` 文件，将以下示例配置粘贴进去，并根据注释修改对应的值：

```yaml
version: "3"

services:
  ironsbot:
    image: ghcr.io/nattsu39/ironsbot:latest
    environment:
      # === 赛尔号数据查询插件，可选择远程同步模式或本地回退模式 ===
      # 远程同步模式
      SEERAPI_SYNC_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/seerapi-data.sqlite"
      ALIAS_SYNC_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/aliases-data.sqlite"

      # 本地回退模式
      SEERAPI_LOCAL_PATH: "seerapi-data.sqlite"
      ALIAS_LOCAL_PATH: "aliases-data.sqlite"

      # --- 可选配置（以下均为默认值） ---
      # SEERAPI_SYNC_INTERVAL_MINUTES: "60"  # 数据同步间隔（分钟）
      # ALIAS_SYNC_INTERVAL_MINUTES: "60"

      # === 表情包插件，当缺少时相关命令将被禁用 ===
      # MEMES_CNB_TOKEN: "你的CNB令牌"
      # MEMES_CNB_REPO: "Nattsu39/tudou"

      # === 机器人配置（必填） ===
      ONEBOT_ACCESS_TOKEN: "你的OneBot token" # 设置OneBot的访问令牌，用于NapCat连接机器人，注意不要泄露给他人

      # --- 机器人配置（以下均为默认值，按需修改） ---
      # HOST: "0.0.0.0"
      # PORT: "8080"                  # 修改后需同步更新上方 ports 映射
      # COMMAND_START: '[""]'
      # SUPERUSERS: '[]'

    restart: always

  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: napcat
    restart: always
    mac_address: 02:42:ac:11:00:02 # 自行设置

    environment:
      - NAPCAT_UID=${NAPCAT_UID}
      - NAPCAT_GID=${NAPCAT_GID}
    
    ports:
      - 6099:6099

    volumes:
      - ./napcat/config:/app/napcat/config
      - ./ntqq:/app/.config/QQ
```

完整的变量说明请参考仓库中的 [`.env.example`](.env.example)。

#### 3. 启动服务

```bash
docker compose up -d
```

查看日志确认启动成功：

```bash
docker compose logs -f
```

#### 4. 初始化 NapCat

在启动 NapCat 后，在 NapCat 容器日志中找到NapCat的登录token，并访问 `http://[你的服务器ip]:6099/webui`，输入token并登录机器人的QQ号。

在 NapCat 的`网络配置`中，新建一个`WebSocket 客户端`，将`URL`设置为：
```
ws://ironsbot:8080/onebot/v11/ws
```
并设置名称，token一栏填写之前设置的OneBot token，最后点击`保存`并启用即可。

### 在 Windows 上部署
待补充

## 协议
本项目采用**多协议**结构，详见 [LICENSING.md](LICENSING.md)：

- **整机 / 完整仓库 / Docker 镜像**：作为"组合作品"对外分发时整体须遵守 **GPL-3.0-or-later**。
- **`get_seer_info`、`headless_seer` 两个插件**：**GPL-3.0-or-later**（见各自目录下的 `LICENSE`）。
- **其余全部代码**（其他插件、`ironsbot/utils`、`bot.py`、`docker/` 等）：**MIT**（见根目录 [LICENSE](LICENSE)）。

也就是说，非插件模块可被单独提取并以 MIT 协议复用；但只要分发包含上述两个 GPL 插件的整机，整体仍受 GPL-3.0 约束。每个源文件顶部均带有 `SPDX-License-Identifier` 标识其协议归属。

其中 `headless_seer` 的 session 获取与登录数据包构建函数改写自 [@oldml](https://github.com/oldml) 的 [saixiaoxi](https://github.com/oldml/saixiaoxi)（MIT），出处声明见 [`ironsbot/plugins/headless_seer/NOTICE`](ironsbot/plugins/headless_seer/NOTICE)。

## ❤️ 特别鸣谢
- [@oldml](https://github.com/oldml)
- [@聿聿](https://github.com/WhY15w)
- [@火火](https://github.com/Yogurt114514)
- [@星空](https://github.com/sptsaixiaoxi)

[**@火火**]: https://github.com/Yogurt114514
