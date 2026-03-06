# 未来需求：用户级卡 Nickname 与按 Nickname 聚合（2026-03-05）

## 1. 需求概述

- **用户级**：每个用户可以为自己的每张卡（payment method / 卡号或卡标识）起一个 **nickname**。
- **聚合视图**：在「By payment type」类统计/报表中，支持按用户自己设置的 nickname 进行 **aggregate**（汇总展示），而不是仅按系统原始卡类型或卡号。

## 2. 功能点

1. **卡 Nickname 管理（用户级）**
   - 用户可维护多张卡，每张卡可设置/修改一个 nickname（如「买菜卡」「公司报销卡」）。
   - 数据需按 user 隔离，且与现有 payment type / 卡信息关联（需明确关联键：卡号尾号、发卡行、或系统生成的 payment_method_id 等）。

2. **By payment type 聚合**
   - 现有或未来的「按支付方式」统计（如按卡、按支付类型）应支持：
     - 按**用户 nickname** 分组/聚合展示；
     - 可选：同时保留按系统原始 payment type 的视图，或提供切换（nickname vs 原始类型）。

## 3. 实现时需考虑

- **数据模型**：用户卡 nickname 的存储（新表或 user 相关扩展）、与 receipt/transaction 的 payment 字段如何关联。
- **多设备/多端**：nickname 需在用户账号下全局一致。
- **隐私**：nickname 仅对当前用户可见，不做跨用户展示。
- **迁移**：已有 receipt 的 payment 信息如何映射到「卡」实体（若当前只有文本或 type 而无稳定卡 ID，可能需要先引入 payment method 实体或稳定标识）。

## 4. 状态

- **状态**：未来需求，待排期。
- **记录日期**：2026-03-05。
