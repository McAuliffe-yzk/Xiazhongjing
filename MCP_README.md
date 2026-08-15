# 匣中镜 MCP Server

匣中镜 MCP 适配层将现有个人创作能力暴露为 Streamable HTTP 工具，业务逻辑继续复用 `application/` 和 `services/`，不复制生成链路。当前部署还会同时挂载创作者 Web 体验页，因此同一个公网服务同时提供网页和 MCP。

## 工具范围

- `creator_identity`：当前个人 DNA 版本、叙事框架和表达边界。
- `parse_creation_materials`：把自然语言输入拆成创作素材。
- `generate_vlog_copy`：使用个人 DNA 生成 Vlog 文案，可选择四种叙事模式、字数和书库金句策略。
- `rewrite_current_copy`：仅针对当前文案重写，不读取原始素材。
- `insert_book_quotes`：从本地书库植入逐字直接引用。
- `book_library_sources`：查看书库来源和素材数量。

## 本地启动

```bash
python3 -m venv .mcp-venv
source .mcp-venv/bin/activate
pip install -r requirements-mcp.txt
MCP_PORT=8080 python mcp_server.py
```

MCP 地址：`http://127.0.0.1:8080/mcp`
Web 体验页：`http://127.0.0.1:8080/xiangzhongjing-demo`

## 环境变量

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 生成类工具必需 | 复用匣中镜现有模型配置 |
| `DEEPSEEK_API_BASE` | 否 | 默认 `https://api.deepseek.com` |
| `MCP_HOST` | 否 | 默认 `0.0.0.0` |
| `MCP_PORT` | 否 | 默认 `8080` |
| `MCP_API_KEY` | 否 | 配置后要求 `Authorization: Bearer <key>`；留空适合赛事无请求头连接 |
| `XIANGZHONGJING_DATA_DIR` | 否 | 默认 `/data`（容器）或本机应用数据目录 |

## Docker

```bash
docker build -f Dockerfile.mcp -t xiangzhongjing-mcp .
docker run --rm -p 8080:8080 --env-file .env \
  -e MCP_HOST=0.0.0.0 -e MCP_PORT=8080 \
  -v "$HOME/Library/Application Support/xiangzhongjing:/data" \
  xiangzhongjing-mcp
```

## Claude Desktop / 本地 stdio

```json
{
  "mcpServers": {
    "xiangzhongjing": {
      "command": "python3",
      "args": ["/绝对路径/匣中镜/mcp_server_stdio.py"],
      "env": {
        "DEEPSEEK_API_KEY": "你的密钥"
      }
    }
  }
}
```

## 公网部署

正式赛事链接必须是稳定公网 HTTPS 地址，例如 `https://your-domain.example/mcp`。创作者体验页使用同一域名的根路径或 `/xiangzhongjing-demo`。容器监听 `0.0.0.0:$PORT`，可直接部署到 Render、Railway、Fly.io 或自有云主机，并挂载持久化 `/data`。

仓库附带 `render.yaml`。在 Render 中创建 Blueprint、连接仓库并填写 `DEEPSEEK_API_KEY` 后，会得到稳定地址：

```text
https://xiangzhongjing-mcp.onrender.com/mcp
```

实际域名以 Render 分配结果为准。部署完成后运行：

```bash
python scripts/verify_mcp.py https://你的域名/mcp
```

部署时不要提交 `.env`、数据库或个人原始文稿；API Key 只通过平台 Secret 注入。

## 无信用卡方案：Hugging Face Spaces

如果 Render 要求绑定信用卡，可以使用 Hugging Face Spaces 的 Docker Space。仓库根目录已提供 `Dockerfile`，默认监听 Hugging Face 需要的 `7860` 端口。

操作步骤：

1. 登录 https://huggingface.co/spaces
2. 点击 `Create new Space`
3. Space SDK 选择 `Docker`
4. Visibility 可先选择 `Public`
5. 创建后进入 `Settings` -> `Repository secrets`
6. 添加：

```text
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEEPSEEK_API_BASE=https://api.deepseek.com
```

7. 将 GitHub 仓库内容同步到 Space，或按 Hugging Face 页面提示将当前仓库 push 到 Space remote。

部署成功后，Space 地址类似：

```text
https://你的用户名-xiazhongjing.hf.space
```

最终 MCP 链接：

```text
https://你的用户名-xiazhongjing.hf.space/mcp
```

验证：

```bash
.mcp-venv/bin/python scripts/verify_mcp.py https://你的用户名-xiazhongjing.hf.space/mcp
```
