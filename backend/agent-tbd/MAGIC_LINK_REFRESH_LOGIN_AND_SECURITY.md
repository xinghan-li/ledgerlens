# Magic Link 与「刷新即登录」体验说明

## 为什么点邮件里的链接会跳到 localhost:3000？（ngrok 时必看）

**原因**：Supabase 规定：你传的 `emailRedirectTo` **必须**出现在 Dashboard 的 **Redirect URLs** 白名单里；否则 Supabase **会忽略我们传的地址**，改用 **Site URL**（默认是 `http://localhost:3000`），所以邮件里的链接就变成 localhost。

**解决办法（两步）**：

1. **在 Supabase 里加白名单**  
   打开：Supabase Dashboard → **Authentication** → **URL Configuration** → **Redirect URLs**。  
   添加你当前用的回调地址，例如：
   - 当前 ngrok 固定子域：`https://你的子域.ngrok-free.app/auth/callback`
   - 或使用**通配符**（推荐，ngrok 子域会变）：`https://*.ngrok-free.app/**` 或 `https://*.ngrok.io/**`（按你实际域名选）
2. **（可选）测试时改 Site URL**  
   若仍跳 localhost，可临时把 **Site URL** 改成当前访问的地址（如 ngrok 或局域网），但**生产环境记得改回正式域名**。

登录页「邮件已发送」下方会显示「本次登录链接将跳回: xxx」，请把该地址（或对应通配符）加入上述 Redirect URLs。

---

## 当前行为

- 用户在登录页输入邮箱 → 我们发 Magic Link（Supabase OTP），`emailRedirectTo` 使用**当前页面 origin**（支持 ngrok/局域网）。
- 用户点击邮件中的链接 → 浏览器请求 `/auth/callback?code=...` → 服务端用 code 换 session，写 cookie，重定向到 `/dashboard`。
- **若点击链接后 404**：说明请求没打到我们的前端（例如链接在 Gmail 内嵌浏览器里打开、或域名/路径不对），callback 从未执行，**同一设备上刷新「发送链接的那个网页」也不会自动登录**，因为 session 从未被写入。

## 能否做到「点邮件链接 404 后，刷新发链接的页面就登录」？

- **技术上**：只有在该设备上**曾经成功完成过一次 Magic Link 回调**（即点击链接后真正打开了我们的 `/auth/callback` 并写入了 session cookie）时，刷新同一浏览器里的页面才会「已经登录」。
- 若链接**从未成功打开**（一直 404），则：
  - 服务端从未收到 `code`，无法换 session；
  - 我们也没有在「请求 Magic Link 时」给该设备发一个可用来直接登录的 token（见下）。
- 所以：**在「链接 404」的前提下，仅靠「刷新发链接的页面」无法实现自动登录**，除非改流程（见下「可选增强」）。

## 常见网站是怎么做的？

1. **Magic Link 必须能打开**
   - 配置正确的 Redirect URLs（含 ngrok/生产域名），确保点邮件链接时能打开 `https://你的域名/auth/callback?code=...`，这样同一浏览器刷新任意页都会已登录。

2. **「记住设备」式体验**
   - 部分网站在你**请求** Magic Link 时，除了发邮件，还会在当前设备设一个**短期 cookie**（如 15 分钟），并可能配合邮件里的 **one-time token**。
   - 当用户**先点了邮件链接**（在任意设备/标签页），链接对应的接口会校验 token、写入 session；若用户随后在**发链接的那台设备**刷新，因为 cookie 和 session 可能在同一域下已同步，看起来像「刷新就登录了」。本质仍是「链接在某处成功打开过」或「同域多标签共享了 session」。

3. **安全要点**
   - 用 **HTTPS**、**短期有效的 code/token**、**一次性使用**（code 换 session 后即失效）。
   - 不在 URL 里长期暴露敏感信息；session 用 httpOnly cookie 存。
   - 这样做的「刷新即登录」是**安全**的，前提是：登录动作仍由「点击邮件里的链接」或「同域下已建立的 session」完成，而不是仅凭一个长期有效的 URL 或未验证的 cookie。

## 建议

- **先保证不 404**：在 Supabase 的 Redirect URLs 里加上你实际使用的 origin（如 ngrok、局域网 IP），并确保登录页的 `emailRedirectTo` 使用当前 origin（已实现）。
- **体验上**：用户应在**同一浏览器**里点邮件链接，这样回调成功后，再刷新发链接的页面自然就是已登录状态。
- 若你希望即使用户在**别的设备/浏览器**点了链接 404，回到原设备「刷新」也能登录，需要**额外设计**（例如：请求 Magic Link 时生成短期 one-time token 并存 cookie；邮件链接落地页先设 cookie 再重定向；或后端提供「用该 token 换 session」的接口）。这属于可选增强，实现时需注意 token 时效与一次性使用以保证安全。

---

## 为什么邮件里的链接是「一次性的」？能做成「7 天内随便点都有效」吗？

### Supabase 的设定

- **一次使用**：Supabase 的 Magic Link（邮件里的登录链接）是**设计成一次性的**，不能改成「可重复使用直到过期」。点一次并成功登录后，该链接即失效；若未点过但过期，也会报 `otp_expired`。
- **安全原因**：防止链接被截获或误发后被人多次使用；一次用完后即作废，风险更可控。
- **过期时间**：默认约 1 小时；可在 **Supabase Dashboard → Authentication → Providers → Email** 里调整 **Email OTP Expiration**，**最长 24 小时**（86,400 秒），不能设成 3～7 天。

所以：**在 Supabase 自带能力下，无法实现「同一个链接在 3～7 天内多次点击都能登录」**。

### 我们能做的

1. **延长有效期到 24 小时**  
   在 Supabase → Auth → Providers → Email 里把 **Email OTP Expiration** 调到最大（例如 86400 秒）。链接仍是一次性的，但至少在 24 小时内「第一次点」都有效。
2. **过期/无效时体验**  
   当用户点到过期或已用过的链接时，Supabase 会重定向到 Site URL 并带上 `error=access_denied&error_code=otp_expired`。我们已做：
   - 首页若带这些参数会重定向到 `/login?error=otp_expired`；
   - 登录页会显示「链接已过期或已使用，请重新输入邮箱获取新链接」，并可直接再发一封。
3. **若一定要「7 天内可多次点」**  
   需要自建一套「长期有效、可多次使用」的链接，例如：
   - 用户请求登录时，我们**自己**生成一个 7 天有效的 token（JWT 或随机 token 存库），发邮件里的链接指向**我们的后端**，例如 `https://你的域名/auth/verify-email?token=xxx`；
   - 用户点击后，后端校验 token 和有效期，再通过 Supabase Admin API 或自定义 JWT 为该用户创建 session，并重定向回前端。
   这样链接在 7 天内可多次使用，但实现和运维成本更高，也需要自己把控 token 安全（泄露范围、撤销等）。
