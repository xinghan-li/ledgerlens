"""
生成商品标准化预览 CSV

用于人工审核标准化规则是否合理
"""
import os
import sys
import io
import csv
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add backend directory to path (scripts moved to backend/scripts/tools/)
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv(dotenv_path=backend_dir / ".env")

from app.services.database.supabase_client import _get_client
from app.services.standardization.product_normalizer import standardize_product


def _complete_item_data(item: dict) -> dict:
    """
    补全商品数据
    
    规则：
    1. 如果没有 unit，且有 unit_price 或 line_total，默认补 "EACH"（按件卖）
    2. 如果 line_total == unit_price（或非常接近），说明 quantity = 1，补全 quantity
    3. 如果只有 line_total 没有 unit_price，推导 unit_price
    """
    quantity = item.get('quantity')
    unit = item.get('unit')
    unit_price = item.get('unit_price')
    line_total = item.get('line_total')
    
    # 规则 1: 补全 unit
    # 如果有价格信息但没有 unit，默认按件卖
    if not unit and (unit_price or line_total):
        item['unit'] = 'EACH'
        unit = 'EACH'
    
    # 规则 2 和 3: 补全 quantity 和 unit_price
    if unit_price and line_total:
        # 如果 unit_price 约等于 line_total（误差 ±0.01），说明 quantity = 1
        if abs(float(unit_price) - float(line_total)) <= 0.01:
            if not quantity:
                item['quantity'] = 1
                quantity = 1
    
    # 规则 3: 如果只有 line_total，推导其他值
    if line_total and not unit_price:
        if not quantity or quantity == 0:
            # 没有数量信息，默认为 1
            item['quantity'] = 1
            quantity = 1
        # 推导单价
        item['unit_price'] = float(line_total) / float(quantity)
    
    return item


print("\n" + "="*80)
print("📊 生成商品标准化预览 CSV")
print("="*80)

supabase = _get_client()

# 1. 获取所有成功的小票
print("\n1. 查询成功的小票...")
receipts = supabase.table("receipt_status")\
    .select("id, user_id, uploaded_at")\
    .eq("current_status", "success")\
    .order("uploaded_at", desc=True)\
    .execute()

print(f"找到 {len(receipts.data)} 张成功的小票")

# 2. 获取所有商品
print("\n2. 提取商品数据...")
all_items = []
receipt_count = 0

for receipt in receipts.data:
    receipt_id = receipt['id']
    
    # 获取 processing run
    runs = supabase.table("receipt_processing_runs")\
        .select("output_payload")\
        .eq("receipt_id", receipt_id)\
        .eq("stage", "llm")\
        .eq("status", "pass")\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    
    if not runs.data:
        continue
    
    output_payload = runs.data[0].get("output_payload", {})
    items = output_payload.get("items", [])
    
    # 获取 store 信息：以 output_payload._metadata 的 location_id / chain_id 为准（workflow 已匹配）
    meta = output_payload.get("_metadata", {})
    store_location_id = meta.get("location_id")
    store_chain_id = meta.get("chain_id")
    
    if items:
        receipt_count += 1
        for item in items:
            item['receipt_id'] = receipt_id
            item['receipt_date'] = receipt.get('uploaded_at', '')[:10]
            item['store_location_id'] = store_location_id
            item['store_chain_id'] = store_chain_id
            all_items.append(item)

print(f"从 {receipt_count} 张小票中提取了 {len(all_items)} 个商品")

# 3. 数据补全和标准化
print("\n3. 应用数据补全和标准化规则...")
standardized_items = []

for item in all_items:
    try:
        # 数据补全逻辑（在标准化之前）
        item = _complete_item_data(item)
        
        # 标准化
        standardized = standardize_product(item)
        standardized['receipt_id'] = item.get('receipt_id')
        standardized['receipt_date'] = item.get('receipt_date')
        standardized['store_location_id'] = item.get('store_location_id')
        standardized['store_chain_id'] = item.get('store_chain_id')
        standardized_items.append(standardized)
    except Exception as e:
        print(f"⚠️  标准化失败: {item.get('product_name')} - {e}")

print(f"成功标准化 {len(standardized_items)} 个商品")

# 4. 生成统计
print("\n4. 生成统计信息...")

# 统计唯一的标准化名称（按 store_location_id 分组，便于与 store 关联）
unique_normalized = {}
for item in standardized_items:
    norm_name = item['normalized_name']
    loc_id = item.get('store_location_id') or ''
    
    if norm_name:
        key = (norm_name, loc_id)
        if key not in unique_normalized:
            unique_normalized[key] = {
                'normalized_name': norm_name,
                'store_location_id': loc_id,
                'store_chain_id': item.get('store_chain_id') or '',
                'count': 0,
                'original_names': set(),
                'brands': set(),
                'categories': set()
            }
        unique_normalized[key]['count'] += 1
        unique_normalized[key]['original_names'].add(item['original_name'])
        if item['brand']:
            unique_normalized[key]['brands'].add(item['brand'])
        if item['category_l2']:
            unique_normalized[key]['categories'].add(item['category_l2'])

print(f"\n📊 统计:")
print(f"  - 原始商品名: {len(set(i['original_name'] for i in standardized_items))}")
print(f"  - 标准化后: {len(unique_normalized)}")
print(f"  - 压缩率: {len(unique_normalized) / len(set(i['original_name'] for i in standardized_items)) * 100:.1f}%")

# 5. 输出 CSV
# 使用项目根目录的 output 文件夹（backend_dir = backend，其 parent = 项目根）
output_dir = backend_dir.parent / "output" / "standardization_preview"
output_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = output_dir / f"standardization_preview_{timestamp}.csv"

print(f"\n5. 生成 CSV: {csv_path}")

with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    fieldnames = [
        'receipt_id',
        'receipt_date',
        'store_location_id',
        'store_chain_id',
        'original_name',
        'normalized_name',
        'brand',
        'category_l1',
        'category_l2',
        'category_l3',
        'quantity',
        'unit',
        'unit_price',
        'line_total',
        'is_on_sale'
    ]
    
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    
    for item in standardized_items:
        writer.writerow({
            'receipt_id': item.get('receipt_id', ''),
            'receipt_date': item.get('receipt_date', ''),
            'store_location_id': item.get('store_location_id', ''),
            'store_chain_id': item.get('store_chain_id', ''),
            'original_name': item.get('original_name', ''),
            'normalized_name': item.get('normalized_name', ''),
            'brand': item.get('brand', ''),
            'category_l1': item.get('category_l1', ''),
            'category_l2': item.get('category_l2', ''),
            'category_l3': item.get('category_l3', ''),
            'quantity': item.get('quantity', ''),
            'unit': item.get('unit', ''),
            'unit_price': item.get('unit_price', ''),
            'line_total': item.get('line_total', ''),
            'is_on_sale': item.get('is_on_sale', '')
        })

print(f"✅ CSV 生成完成: {len(standardized_items)} 行")

# 6. 生成汇总 CSV（按标准化名称分组）
summary_path = output_dir / f"standardization_summary_{timestamp}.csv"

print(f"\n6. 生成汇总 CSV: {summary_path}")

with open(summary_path, 'w', newline='', encoding='utf-8-sig') as f:
    fieldnames = [
        'normalized_name',
        'store_location_id',
        'store_chain_id',
        'count',
        'original_names',
        'brands',
        'category_l1',
        'category_l2',
        'category_l3',
        'example_price'
    ]
    
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    
    for key, stats in sorted(unique_normalized.items(), key=lambda x: x[1]['count'], reverse=True):
        norm_name = stats['normalized_name']
        loc_id = stats.get('store_location_id', '')
        
        example = next((i for i in standardized_items
                       if i['normalized_name'] == norm_name
                       and (i.get('store_location_id') or '') == loc_id), None)
        example_price = example.get('unit_price', '') if example else ''
        example_cat_l1 = example.get('category_l1', '') if example else ''
        example_cat_l2 = example.get('category_l2', '') if example else ''
        example_cat_l3 = example.get('category_l3', '') if example else ''
        
        writer.writerow({
            'normalized_name': norm_name,
            'store_location_id': loc_id,
            'store_chain_id': stats.get('store_chain_id', ''),
            'count': stats['count'],
            'original_names': ' | '.join(sorted(stats['original_names'])),
            'brands': ' | '.join(sorted(stats['brands'])),
            'category_l1': example_cat_l1,
            'category_l2': example_cat_l2,
            'category_l3': example_cat_l3,
            'example_price': example_price
        })

print(f"✅ 汇总 CSV 生成完成: {len(unique_normalized)} 行")

# 7. 生成分类统计
category_stats = {}
for item in standardized_items:
    cat_key = f"{item.get('category_l1', 'Unknown')} > {item.get('category_l2', 'Unknown')}"
    if cat_key not in category_stats:
        category_stats[cat_key] = 0
    category_stats[cat_key] += 1

print("\n📊 分类统计:")
for cat, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
    print(f"  {cat}: {count}")

print("\n" + "="*80)
print("✅ 完成！")
print("="*80)
print(f"\n📁 输出文件:")
print(f"  1. 详细数据: {csv_path}")
print(f"  2. 汇总数据: {summary_path}")
print(f"\n💡 下一步:")
print(f"  1. 用 Excel 打开这些 CSV 文件")
print(f"  2. 检查 normalized_name 是否合理")
print(f"  3. 检查 brand 和 category 是否正确")
print(f"  4. 如果需要调整，修改 product_normalizer.py")
print(f"  5. 重新运行此脚本生成新的 CSV")
print(f"  6. 确认无误后，运行 categorization API 导入数据")
print()
