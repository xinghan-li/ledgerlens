# 上生产环境前检查清单

上线公网前请逐项确认：

## CORS
- [ ] 将 `backend/app/main.py` 中 `CORSMiddleware` 的 `allow_origins` 改为**仅包含你的前端域名**（例如 `["https://yourdomain.com"]`），不要使用 `["*"]` 或包含 localhost。
- [ ] 建议通过环境变量配置（如 `CORS_ORIGINS`），便于不同环境切换。

## HTTPS
- [ ] 生产环境全站使用 HTTPS；Firebase / 前端仅在 HTTPS 下使用。

## 敏感配置
- [ ] `.env`、Firebase 服务账号 JSON、Supabase JWT secret 等不提交到仓库、不暴露给前端或日志。
- [ ] 生产环境使用环境变量或密钥管理服务。

## 错误信息
- [ ] 生产环境关闭或脱敏详细 stack trace，避免暴露路径与依赖版本。

## 其他
- [ ] 确认 admin / super_admin 名单仅包含可信账号。
- [ ] 多实例部署时，限流需使用 Redis 等共享存储（当前为单实例内存限流）。

---
*本清单在实现限流、重复上传与 receipt 校验时创建，上公网前请按此检查。*
