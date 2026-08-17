# 匣中镜 Xiangzhongjing

匣中镜是一套面向单个内容创作者的本地优先 Personal Agent。它把历史文稿蒸馏为可审核的个人 DNA，用真实素材生成第一人称 Vlog 文案，并通过镜中人、书中人和长期记忆继续理解创作者。

当前公开版本是 **Community Beta v0.4.1**：让新用户从一个不含维护者私有数据的空白安装出发，完成模型验证、个人 DNA、精神书库、镜中人、书中人、每日灵感与第一篇真实创作。

## 核心能力

- 项目、素材、文案版本、发布日记与封面资产管理
- 可审核、可回退的个人创作 DNA Skill
- 默认、排比递进、六段式、先抑后扬四种叙事模式
- 原句、改写、阐释三种素材表达边界与严格字数约束
- 可导入任意书籍、原文和阅读笔记的本地精神书库
- 只允许已确认直接引文参与生成的书库质量工作流
- 镜中人长期记忆：历史原文片段、跨会话摘要和人工确认记忆
- 可从一本或多本个人书籍创建、修改和归档书中人
- 对话证据链与“像我 / 不像我 / 记住 / 忘掉”校准反馈
- 基于个人 DNA、历史记忆、近期项目与有效书库的每日灵感匣签
- 灵感有效性反馈、近 14 天转化与发布指标，以及生成耗时观测
- 七步首次使用检查：模型、身份、DNA、书库、镜中人、书中人、首篇创作
- 可选 Streamable HTTP MCP 服务

## 快速开始

需要 Python 3.9 或更高版本。

macOS / Linux：

```bash
python3 scripts/bootstrap.py --start
```

Windows PowerShell：

```powershell
py scripts\bootstrap.py --start
```

访问 [http://127.0.0.1:8860/xiangzhongjing-demo](http://127.0.0.1:8860/xiangzhongjing-demo)。首次安装会进入“开始使用”，空白创作者档案不会预装维护者的项目、书籍、人物或历史文稿。

## 首次建立自己的匣中镜

1. 在“设置”填写兼容 OpenAI Chat Completions 的模型配置，并执行真实连接测试。
2. 在“个人信息”填写名称、创作定位、栏目和表达关键词。
3. 在“内容蒸馏”批量导入 DOCX、PDF、TXT 或 Markdown 历史文案，审核并发布候选 DNA。
4. 在“精神书库”创建自己的书籍，上传原文或阅读笔记，并确认允许直接引用的候选句。
5. 新建项目，选择允许调用的书籍，录入真实素材并生成第一篇文案。
6. 镜中人会自动使用已发布 DNA 与历史文稿记忆；书中人由用户从已导入书籍创建。

“开始使用”页会实时显示以上能力是否真正就绪，而不是只判断输入框是否填写。

## Docker

```bash
docker compose up --build
```

Web 页面运行在 `http://127.0.0.1:8860/xiangzhongjing-demo`，数据保存在命名卷 `xiangzhongjing-data`。

需要同时验证 MCP 时：

```bash
docker compose --profile mcp up --build
```

MCP 地址为 `http://127.0.0.1:8080/mcp`。Web 与 MCP 同时写同一个 SQLite 数据卷只适合本地单用户验证，不应作为多用户生产部署。

## 模型配置

复制 `.env.example` 为 `.env`，或启动后在“设置”页填写。至少需要：

```text
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
```

可选能力：

- `TAVILY_API_KEY`：仅用于书中人按需联网补充来源。
- `IMAGE_API_KEY`：用于封面图生成。
- `MCP_API_KEY`：为自建 MCP 增加 Bearer 鉴权。

密钥不会进入备份文件，也不应提交到 Git。

## 个人记忆引擎

历史文稿保存在本地 SQLite，按约 700 字切块并建立 FTS5 索引。镜中人每次只召回与当前问题最相关的 6-10 条依据，不会把全部文稿塞进提示词。回答会保存本轮实际使用的来源；界面只展示来源证据和执行阶段，不展示或伪造模型隐藏思维过程。

跨会话摘要采用增量更新：会话达到 18 条消息后首次总结，此后每新增 12 条消息才刷新一次。用户主动点击“记住”的回复进入全局长期记忆，点击“忘掉”后停止参与后续召回。

## 数据与隐私

默认数据目录：

- macOS：`~/Library/Application Support/xiangzhongjing`
- Windows：`%LOCALAPPDATA%\Xiangzhongjing`
- Linux：`~/.local/share/xiangzhongjing`

可通过 `XIANGZHONGJING_DATA_DIR` 覆盖。数据库、API Key、历史文稿、对话、图片和个人 Profile Pack 均不属于公开源码。

备份：

```bash
python scripts/backup_xiangzhongjing.py
```

恢复前先停止服务：

```bash
python scripts/restore_xiangzhongjing.py backups/your-backup.zip --yes
```

## 开发与测试

```bash
python -m unittest discover -s tests -v
python -m py_compile main.py mcp_server.py api/*.py application/*.py services/*.py tests/*.py
```

前端语法检查：

```bash
for file in static/js/*.js; do node --check "$file"; done
```

项目采用模块化单体：FastAPI 路由位于 `api/`，用例边界位于 `application/`，领域服务位于 `services/`，SQLite 负责本地持久化，原生前端按业务域拆分在 `static/js/`。

## 发布边界

公开仓库只提供通用创作者基线和合成空白状态。维护者的历史文稿、私人对话、书籍文件、数据库和正式个人 Skill 必须通过独立加密 Profile Pack 交付，不得进入 GitHub 历史。

从现有私人工作区生成经过排除规则检查的 Community Beta 包：

```bash
./scripts/package_community_beta.sh v0.4.1-beta
```

更多说明见 [Community Beta 指南](docs/COMMUNITY_BETA.md) 和 [架构说明](docs/ARCHITECTURE.md)。

## License

代码以 [Apache License 2.0](LICENSE) 开源。“匣中镜 / Xiangzhongjing”的名称和品牌标识不随代码授权，详见 [TRADEMARKS.md](TRADEMARKS.md)。
