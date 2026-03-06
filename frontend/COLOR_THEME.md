# LedgerLens 主题色板

> 做 UI / 样式 / 按钮 / 配色时请**只使用本主题色**，保证与 landing / dashboard 一致。

---

## 色板一览

### 黑
| Hex | Tailwind 名称 | 说明 |
|-----|----------------|------|
| `#000000` | `theme-black` | 纯黑 |
| `#191919` | `theme-slate` | 深灰黑 |
| `#262625` | `theme-dark-262` | 深色 |
| `#40403e` | `theme-dark-404` | 中深色 |

### 灰
| Hex | Tailwind 名称 | 说明 |
|-----|----------------|------|
| `#666663` | `theme-gray-666` | 中灰 |
| `#91918d` | `theme-gray-919` | 浅灰 |
| `#bfbfba` | `theme-cloud` | 云灰 |

### 白
| Hex | Tailwind 名称 | 说明 |
|-----|----------------|------|
| `#e5e4df` | `theme-ivory-dark` | 深象牙 |
| `#f0f0eb` | `theme-cream-f0` | 奶油底 |
| `#fafaf7` | `theme-ivory` | 象牙白 |
| `#ffffff` | `white` | 纯白 |

### 橙
| Hex | Tailwind 名称 | 说明 |
|-----|----------------|------|
| `#cc785c` | `book-cloth` | 主橙（主操作按钮等） |
| `#d4a27f` | `theme-orange-mid` | 中橙 |
| `#ebdbbc` | `manilla` | 浅橙/米色 |

### 其他
| 名称 | Hex / 来源 | Tailwind 用法 | 说明 |
|------|------------|----------------|------|
| 蓝 | `#61aaf2` | `theme-blue` | 链接、信息 |
| 红 | `#bf4d43` | `theme-red` | 危险、删除、错误 |
| 绿 | Tailwind 默认 | `green-*` | 成功态 |
| 黄 | Tailwind 默认 | `amber-*` / `yellow-*` | 警告等 |

---

## 在代码中的用法

- **Tailwind**：`globals.css` 的 `@theme` 与 `tailwind.config.js` 已扩展，可直接用：
  - 黑：`bg-theme-black`、`text-theme-slate`、`border-theme-dark-404`
  - 灰：`text-theme-gray-666`、`bg-theme-cloud`
  - 白：`bg-theme-ivory`、`bg-theme-cream-f0`、`bg-white`
  - 橙：`bg-book-cloth`、`text-theme-orange-mid`、`bg-manilla`
  - 其他：`bg-theme-blue`、`text-theme-red`、`bg-red-600` 改为 `bg-theme-red`
- **语义**：
  - **主操作**：背景 `book-cloth` (#cc785c)，文字 `theme-ivory` (#fafaf7)。
  - **次操作**：背景 `theme-slate` (#191919)，文字 `theme-ivory`。
  - **危险/删除/错误**：`theme-red` (#bf4d43)。
  - **链接/信息**：`theme-blue` (#61aaf2)。
  - **成功**：Tailwind `green-*`；**警告**：Tailwind `amber-*` / `yellow-*`。

---

## 项目内引用

- `frontend/app/globals.css`：`@theme` 中定义全部主题色
- `frontend/tailwind.config.js`：`theme.extend.colors` 扩展
