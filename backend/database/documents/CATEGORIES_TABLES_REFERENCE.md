# categories 与 category_migration_mapping 表说明

## 1. `categories` 表（层级分类树）

用途：用树形结构做商品分类，替代原来的扁平 category_l1/l2/l3，支持任意层级、后续扩展用户自定义分类。

| 字段 | 类型 | 含义 |
|------|------|------|
| **id** | UUID | 主键，分类唯一标识 |
| **parent_id** | UUID, FK→categories(id) | 父分类 ID；根节点为 NULL |
| **level** | INT | 层级深度：1=根（如 Grocery），2=二级，3=三级…（约束 1–10） |
| **name** | TEXT | 展示用名称，如 "Grocery", "Produce", "Fruit" |
| **normalized_name** | TEXT | 小写、用于匹配的名称，如 "grocery", "produce" |
| **path** | TEXT | 从根到当前节点的路径，便于查询，如 `Grocery/Produce/Fruit` |
| **display_order** | INT | 同级下的展示顺序，数字越小越靠前 |
| **icon** | TEXT | 图标：当前 seed 里存的是 **emoji**（见下） |
| **color** | TEXT | 前端用颜色，如 hex |
| **description** | TEXT | 可选说明 |
| **is_system** | BOOLEAN | 是否系统预置（true）还是用户自定义（false） |
| **is_active** | BOOLEAN | 是否启用 |
| **product_count** | INT | 该分类下商品数（含子节点，可由 trigger/job 维护） |
| **created_at**, **updated_at** | TIMESTAMPTZ | 创建/更新时间 |

### 关于 icon 和 emoji

- Migration 015 的 **seed 数据**里，`icon` 列直接存了 emoji（如 🛒、🏠、💄、🐾、💊、📦）。
- 建表注释写的是 “Icon name or emoji”，所以当前实现是“名字或 emoji”二选一，seed 选了 emoji。
- 若你希望统一用图标名/代码（例如 `shopping_cart`, `home`），可以：
  - 写一次数据迁移：把现有 emoji 映射成你们前端的 icon key；
  - 或改 seed：新环境直接用 icon name，不再用 emoji。

---

## 2. `category_migration_mapping` 表（旧扁平 → 新树映射）

用途：**数据迁移**时，把旧的“扁平三列”分类（category_l1, category_l2, category_l3）映射到新树结构里某个 `categories.id`。

| 字段 | 类型 | 含义 |
|------|------|------|
| **old_l1** | TEXT | 旧 schema 的一级分类名，如 `'Grocery'` |
| **old_l2** | TEXT | 旧 schema 的二级分类名，如 `'Produce'` |
| **old_l3** | TEXT | 旧 schema 的三级分类名，如 `'Fruit'` |
| **new_category_id** | UUID, FK→categories(id) | 对应的新树节点（叶子或任意层级） |
| **created_at** | TIMESTAMPTZ | 创建时间 |
| **(old_l1, old_l2, old_l3)** | — | 联合主键，保证旧的三元组唯一对应一个新 id |

使用方式：迁移 `receipt_items` 等表的 category_l1/l2/l3 时，用 (old_l1, old_l2, old_l3) 查这条表得到 `new_category_id`，再写入新表或新字段。  
当前 015 里只插入了少量映射（如 Grocery/Produce/Fruit → Grocery/Produce/Fruit 的 id），其余可按需补充。

---

## 3. 小结

- **categories**：新分类树；`icon` 目前在 seed 里是 emoji，可改为 icon name/code 以符合你的设想。
- **category_migration_mapping**：仅用于从“旧扁平 l1/l2/l3”迁移到“新树 category_id”的映射表，不是业务主数据。
