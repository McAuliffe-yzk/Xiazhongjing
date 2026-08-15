# Contributing

感谢参与匣中镜。提交变更前请先确认它服务于“一个具体创作者的本地创作流程”，并保持单用户、本地优先的产品边界。

## 开发流程

1. Fork 仓库并创建功能分支。
2. 使用空白数据目录启动：`XIANGZHONGJING_DATA_DIR=/tmp/xzj-dev python main.py`。
3. 为行为变更增加聚焦测试。
4. 运行完整测试、Python 编译和前端语法检查。
5. PR 中说明用户问题、数据迁移、隐私影响和回滚方式。

## 代码原则

- 不提交真实用户文稿、会话、图片、数据库或密钥。
- 不把某位创作者的姓名、经历或语言习惯硬编码进通用逻辑。
- 模型输出必须经过稳定契约验证，失败时不以伪造模板冒充成功。
- 展示来源证据和执行状态，不展示或伪造隐藏思维链。
- 新依赖必须证明其必要性；优先沿用模块化单体和 SQLite。

## 提交检查

```bash
python -m unittest discover -s tests -v
python -m py_compile main.py mcp_server.py api/*.py application/*.py services/*.py tests/*.py
for file in static/js/*.js; do node --check "$file"; done
```
