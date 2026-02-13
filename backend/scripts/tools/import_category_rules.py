"""
导入分类规则从修正后的 CSV

用法:
  python import_category_rules.py --csv ../output/standardization_preview/standardization_summary_corrected.csv
  
逻辑:
  - 读取 CSV 中的 normalized_name 和 category_l1/l2/l3
  - 空值 = 保留原值（不更新）
  - 有值 = 更新分类
  - 在数据库中查找对应的 category_id
  - 插入或更新 product_categorization_rules 表
"""
import os
import sys
import io
import csv
import argparse
from pathlib import Path
from typing import Dict, Optional, List
from dotenv import load_dotenv

# Add backend directory to path (scripts moved to backend/scripts/tools/)
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv(dotenv_path=backend_dir / ".env")

from app.services.database.supabase_client import _get_client

print("\n" + "="*80)
print("📥 导入分类规则")
print("="*80)


def find_category_id(supabase, l1: Optional[str], l2: Optional[str], l3: Optional[str]) -> Optional[str]:
    """
    根据 category_l1/l2/l3 查找 category_id
    
    查找策略:
    1. 如果有 l3，优先查找 l3
    2. 如果只有 l2，查找 l2
    3. 如果只有 l1，查找 l1
    """
    # 策略 1: 查找最具体的层级
    if l3:
        result = supabase.table("categories")\
            .select("id, name, level, parent_id")\
            .eq("name", l3)\
            .eq("level", 3)\
            .execute()
        
        if result.data:
            # 如果有多个同名 l3（不同 parent），需要验证 parent
            if len(result.data) == 1:
                return result.data[0]['id']
            
            # 多个同名，需要通过 l2 和 l1 验证
            for cat in result.data:
                # 获取 parent (l2)
                if l2 and cat['parent_id']:
                    parent = supabase.table("categories")\
                        .select("id, name, parent_id")\
                        .eq("id", cat['parent_id'])\
                        .single()\
                        .execute()
                    
                    if parent.data and parent.data['name'] == l2:
                        # 如果还需要验证 l1
                        if l1 and parent.data['parent_id']:
                            grandparent = supabase.table("categories")\
                                .select("name")\
                                .eq("id", parent.data['parent_id'])\
                                .single()\
                                .execute()
                            
                            if grandparent.data and grandparent.data['name'] == l1:
                                return cat['id']
                        else:
                            # 不需要验证 l1，或者 l2 是顶层
                            return cat['id']
            
            # 无法验证 parent，返回第一个
            print(f"  ⚠️  多个同名 L3 '{l3}'，无法精确匹配，使用第一个")
            return result.data[0]['id']
    
    # 策略 2: 只有 l2
    if l2 and not l3:
        result = supabase.table("categories")\
            .select("id, name, level, parent_id")\
            .eq("name", l2)\
            .eq("level", 2)\
            .execute()
        
        if result.data:
            if len(result.data) == 1:
                return result.data[0]['id']
            
            # 多个同名 l2，通过 l1 验证
            if l1:
                for cat in result.data:
                    if cat['parent_id']:
                        parent = supabase.table("categories")\
                            .select("name")\
                            .eq("id", cat['parent_id'])\
                            .single()\
                            .execute()
                        
                        if parent.data and parent.data['name'] == l1:
                            return cat['id']
            
            print(f"  ⚠️  多个同名 L2 '{l2}'，无法精确匹配，使用第一个")
            return result.data[0]['id']
    
    # 策略 3: 只有 l1
    if l1 and not l2 and not l3:
        result = supabase.table("categories")\
            .select("id")\
            .eq("name", l1)\
            .eq("level", 1)\
            .single()\
            .execute()
        
        if result.data:
            return result.data['id']
    
    return None


def import_rules_from_csv(csv_path: str, user_id: Optional[str] = None) -> Dict[str, int]:
    """
    从 CSV 导入分类规则
    
    Returns:
        统计信息: {'created': N, 'updated': N, 'skipped': N, 'errors': N}
    """
    supabase = _get_client()
    stats = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    
    print(f"\n1. 读取 CSV: {csv_path}")
    
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return stats
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"   找到 {len(rows)} 行数据")
    
    print("\n2. 处理每一行...")
    
    for i, row in enumerate(rows, 1):
        normalized_name = row.get('normalized_name', '').strip()
        
        if not normalized_name:
            print(f"  {i}. ⏭️  跳过（没有 normalized_name）")
            stats['skipped'] += 1
            continue
        
        # 读取 store 信息
        store_name = row.get('store_name', '').strip() or None
        store_chain_id = None
        
        # 如果有 store_name，查找 store_chain_id
        if store_name:
            try:
                store = supabase.table("store_chains")\
                    .select("id")\
                    .eq("name", store_name)\
                    .single()\
                    .execute()
                
                if store.data:
                    store_chain_id = store.data['id']
            except Exception:
                # Store not found, create universal rule
                pass
        
        # 读取分类
        cat_l1 = row.get('category_l1', '').strip() or None
        cat_l2 = row.get('category_l2', '').strip() or None
        cat_l3 = row.get('category_l3', '').strip() or None
        
        # 如果三个都为空，跳过（用户没有改动）
        if not cat_l1 and not cat_l2 and not cat_l3:
            print(f"  {i}. ⏭️  跳过: {normalized_name}（未修改分类）")
            stats['skipped'] += 1
            continue
        
        # 查找 category_id
        category_id = find_category_id(supabase, cat_l1, cat_l2, cat_l3)
        
        if not category_id:
            print(f"  {i}. ❌ 错误: {normalized_name} → 找不到分类 ({cat_l1}/{cat_l2}/{cat_l3})")
            stats['errors'] += 1
            continue
        
        # 读取原始名称示例
        original_names = row.get('original_names', '').split('|')
        original_names = [name.strip() for name in original_names if name.strip()]
        
        # 检查规则是否已存在（考虑 store_chain_id）
        query = supabase.table("product_categorization_rules")\
            .select("id, category_id")\
            .eq("normalized_name", normalized_name)
        
        if store_chain_id:
            query = query.eq("store_chain_id", store_chain_id)
        else:
            query = query.is_("store_chain_id", "null")
        
        existing = query.execute()
        
        if existing.data:
            # 规则已存在
            rule = existing.data[0]
            
            # 检查 category_id 是否变化
            if rule['category_id'] == category_id:
                store_info = f" @ {store_name}" if store_name else " (通用)"
                print(f"  {i}. ⏭️  跳过: {normalized_name}{store_info}（规则已存在且相同）")
                stats['skipped'] += 1
            else:
                # 更新规则
                supabase.table("product_categorization_rules")\
                    .update({
                        'category_id': category_id,
                        'original_examples': original_names,
                        'updated_at': 'NOW()'
                    })\
                    .eq("id", rule['id'])\
                    .execute()
                
                store_info = f" @ {store_name}" if store_name else " (通用)"
                print(f"  {i}. ✅ 更新: {normalized_name}{store_info} → {cat_l1}/{cat_l2}/{cat_l3}")
                stats['updated'] += 1
        else:
            # 创建新规则
            rule_data = {
                'normalized_name': normalized_name,
                'category_id': category_id,
                'original_examples': original_names,
                'match_type': 'fuzzy',
                'similarity_threshold': 0.90,
                'source': 'manual',
                'priority': 50,  # Manual rules have higher priority than auto
                'created_by': user_id
            }
            
            # 如果有 store_chain_id，创建 store-specific 规则
            if store_chain_id:
                rule_data['store_chain_id'] = store_chain_id
                rule_data['priority'] = 40  # Store-specific rules have even higher priority
            
            supabase.table("product_categorization_rules")\
                .insert(rule_data)\
                .execute()
            
            store_info = f" @ {store_name}" if store_name else " (通用)"
            print(f"  {i}. ✅ 创建: {normalized_name}{store_info} → {cat_l1}/{cat_l2}/{cat_l3}")
            stats['created'] += 1
    
    return stats


def main():
    parser = argparse.ArgumentParser(description='导入分类规则从 CSV')
    parser.add_argument('--csv', required=True, help='CSV 文件路径')
    parser.add_argument('--user-id', help='用户 ID（可选）')
    
    args = parser.parse_args()
    
    stats = import_rules_from_csv(args.csv, args.user_id)
    
    print("\n" + "="*80)
    print("📊 导入统计:")
    print("="*80)
    print(f"  ✅ 创建: {stats['created']}")
    print(f"  🔄 更新: {stats['updated']}")
    print(f"  ⏭️  跳过: {stats['skipped']}")
    print(f"  ❌ 错误: {stats['errors']}")
    print()
    
    if stats['errors'] == 0:
        print("✅ 所有规则导入成功！")
        print()
        print("💡 下一步:")
        print("  1. 运行 python generate_standardization_preview.py")
        print("  2. 查看新生成的 CSV，验证分类是否正确")
        print("  3. 如果还有错误，继续修改 CSV 并重新导入")
    else:
        print(f"⚠️  有 {stats['errors']} 个错误，请检查日志")


if __name__ == "__main__":
    main()
