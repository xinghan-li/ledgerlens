# 🎯 LedgerLens Frontend - 你需要完成的配置

前端已搭建完成并运行在：**http://localhost:3001** ✅

---

## 📋 必须完成的配置（按顺序）

### 1️⃣ 创建环境变量文件

**文件路径**: `frontend/.env.local`

复制以下内容并填入你的 Supabase 信息：

```env
# Supabase 配置（从 Supabase Dashboard 获取）
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here

# 后端 API（可选，默认值如下）
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**获取方式**：

1. 登录 https://app.supabase.com
2. 选择项目
3. **Settings** → **API**
4. 复制 **Project URL** 和 **anon public** key

---

### 2️⃣ 在 Supabase 添加 Redirect URL

**步骤**：

1. Supabase Dashboard → **Authentication** → **URL Configuration**
2. 在 **Redirect URLs** 添加：
   ```
   http://localhost:3001/auth/callback
   ```
3. 保存

---

### 3️⃣ 测试登录流程

1. 访问 http://localhost:3001
2. 点击"登录"
3. 输入邮箱
4. 检查邮箱，点击登录链接
5. 应该自动跳转到 Dashboard ✅

---

## 🎨 完成配置后的下一步

前端已实现基础功能：

- ✅ Magic Link 登录
- ✅ Dashboard 界面
- ✅ 小票上传（连接后端 API）
- ✅ 路由保护

**准备好你的前端设计草稿，我们一起实现完整的界面！**

---

## 📞 遇到问题？

详细配置说明和常见问题解答，请查看：

👉 **`SETUP_GUIDE.md`**

---

**配置完成后，告诉我并发送设计稿，咱们继续开发！🚀**
