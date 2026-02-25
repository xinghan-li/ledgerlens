d# 左侧 / 右侧「顶 → 分割线」高度清单

Tailwind 默认 1rem = 16px。以下到「分割线」或「Category 行」为止，从上到下所有参与高度的 padding/margin/内容。

---

## 左侧（到虚线分割线为止）

| 顺序 | 元素 | Class / 说明 | 高度 / 数值 |
|------|------|----------------|-------------|
| 0 | 展开区容器 | `border-t ... p-4` | **padding-top: 1rem**（左右共用，网格在 p-4 内） |
| 1 | 左卡片 | `rounded-lg p-4` | **padding-top: 1rem**（仅左侧有） |
| 2 | Section1 容器 | `min-h-22` | min-height = **5.5rem** |
| 2a | Section1 内容 | 店名 1 行 + 地址 N 行 + 电话 0/1 行，`text-sm` 行高约 1.25rem | 内容高度 = **(1 + addressLines + (phone?1:0)) × 1.25rem**，与 min-h-22 取大 |
| 2b | 分割线所在 div | `border-t border-dashed ... my-2 pt-2` | **margin-top: 0.5rem** + **padding-top: 0.5rem** + **border-top: 1px** → 合起来约 **1.0625rem** |

**左侧总高度（从网格顶到分割线）**  
= 1rem（左卡 p-4） + max(5.5rem, lineCount×1.25rem) + 1.0625rem  

其中 lineCount = 1 + addressLines.length + (rec?.merchant_phone ? 1 : 0)。

---

## 右侧（到「Category」这一行为止）

| 顺序 | 元素 | Class / 说明 | 高度 / 数值 |
|------|------|----------------|-------------|
| 0 | 展开区容器 | 同上 | 同上（左右共用） |
| 1 | 右卡片 | `border ... rounded-lg` | **无 padding**（与左侧不同） |
| 2 | Classification 标题行 | `px-3 py-2 border-b ...` | **padding-top: 0.5rem** + 一行文字(text-xs ≈ 0.75rem) + **padding-bottom: 0.5rem** → 约 **1.75rem** |
| 3 | 留白 div | 当前用公式算的 minHeight | 应为：左侧总高度 − 1.75rem（见下） |
| 4 | 「Category」行容器 | `px-3 mt-2 pt-2 min-h-7` | margin-top: 0.5rem, padding-top: 0.5rem（这一行本身是「Category」行起点） |

**右侧总高度（从网格顶到「Category」行起点）**  
= 1.75rem（标题行） + whitespaceRem  

要让「Category」与左侧分割线对齐，需要：  
**1.75 + whitespaceRem = 1 + max(5.5, lineCount×1.25) + 1.0625**  
⇒ **whitespaceRem = 1 + max(5.5, lineCount×1.25) + 1.0625 − 1.75 = max(5.5, lineCount×1.25) + 0.3125**

之前错误：  
1. 没有加左侧卡片的 **1rem** padding；  
2. 用了 2.25rem 当标题高度，实际约 **1.75rem**。  
因此留白偏大，Category 行被压得太下。
