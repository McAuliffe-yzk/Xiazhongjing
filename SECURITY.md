# Security Policy

## Supported Versions

当前只为最新 Community Beta 小版本提供安全修复。

## Reporting

请通过 GitHub Security Advisory 私下报告漏洞，不要在公开 Issue 中提交 API Key、数据库、私人文稿或可复现的用户数据。

报告应包含影响范围、复现步骤、受影响版本和建议缓解方式。维护者会在 7 天内确认收到，并在完成修复与披露协调后公开说明。

## Deployment Notes

- 本地版默认绑定 `127.0.0.1`，不要直接暴露到不可信网络。
- 公网部署必须增加认证、HTTPS、访问日志脱敏和独立密钥管理。
- 设置页中的密钥仅适合单用户本地环境，不是多租户密钥保险库。
- MCP 公网部署应配置 `MCP_API_KEY` 和允许的 Host。
- 备份包含个人创作数据，应通过受信任渠道保存；备份不包含 `.env`。
