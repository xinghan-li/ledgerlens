"""
清理重复的小票

这个脚本会：
1. 检测数据库中的重复小票（基于 file_hash 或内容相似度）
2. 保留最早上传的那张小票
3. 删除重复的小票及相关数据（receipt_items, receipt_summaries, receipt_processing_runs）

运行前建议：
1. 备份数据库
2. 先运行 --dry-run 模式查看会删除哪些数据
3. 确认无误后再运行实际删除

使用方法：
    # 查看会删除什么（不实际删除）
    python clean_duplicate_receipts.py --dry-run
    
    # 实际删除重复数据
    python clean_duplicate_receipts.py
    
    # 基于 user_id 清理某个用户的重复数据
    python clean_duplicate_receipts.py --user-id uuid-here
"""
import os
import sys
import io
from dotenv import load_dotenv
from supabase import create_client
from typing import List, Dict, Any
import argparse
from datetime import datetime

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
    sys.exit(1)

# Create Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def find_duplicate_receipts(user_id: str = None) -> List[Dict[str, Any]]:
    """
    查找重复的小票（基于 file_hash）
    
    Returns:
        List of duplicate groups, each containing:
        {
            'file_hash': 'hash_value',
            'count': 3,
            'receipts': [
                {'id': 'uuid', 'uploaded_at': 'timestamp', 'current_status': 'success'},
                ...
            ]
        }
    """
    print("\n" + "="*60)
    print("🔍 查找重复小票...")
    print("="*60)
    
    # Query to find file_hashes that appear more than once
    query = """
    SELECT 
        file_hash,
        COUNT(*) as count,
        ARRAY_AGG(
            json_build_object(
                'id', id,
                'user_id', user_id,
                'uploaded_at', uploaded_at,
                'current_status', current_status,
                'current_stage', current_stage,
                'raw_file_url', raw_file_url
            ) ORDER BY uploaded_at ASC
        ) as receipts
    FROM receipts
    WHERE file_hash IS NOT NULL
    """
    
    if user_id:
        query += f" AND user_id = '{user_id}'"
    
    query += """
    GROUP BY file_hash
    HAVING COUNT(*) > 1
    ORDER BY COUNT(*) DESC, file_hash;
    """
    
    try:
        # Use RPC to execute raw SQL
        result = supabase.rpc('exec_raw_sql', {'sql': query}).execute()
        duplicates = result.data if result.data else []
        
        if not duplicates:
            # Try alternative method: query all receipts and find duplicates in Python
            print("⚠️  RPC method failed, using alternative method...")
            where_clause = f".eq('user_id', '{user_id}')" if user_id else ""
            
            all_receipts_query = supabase.table("receipts").select("id, user_id, file_hash, uploaded_at, current_status, current_stage, raw_file_url").order("uploaded_at")
            if user_id:
                all_receipts_query = all_receipts_query.eq("user_id", user_id)
            
            all_receipts = all_receipts_query.execute()
            
            # Group by file_hash
            hash_groups = {}
            for receipt in all_receipts.data:
                file_hash = receipt.get('file_hash')
                if file_hash:
                    if file_hash not in hash_groups:
                        hash_groups[file_hash] = []
                    hash_groups[file_hash].append(receipt)
            
            # Find groups with more than 1 receipt
            duplicates = []
            for file_hash, receipts in hash_groups.items():
                if len(receipts) > 1:
                    duplicates.append({
                        'file_hash': file_hash,
                        'count': len(receipts),
                        'receipts': receipts
                    })
            
            # Sort by count descending
            duplicates.sort(key=lambda x: x['count'], reverse=True)
        
        return duplicates
    except Exception as e:
        print(f"❌ Error finding duplicates: {e}")
        return []


def get_receipt_related_data_count(receipt_id: str) -> Dict[str, int]:
    """获取某个小票的关联数据数量"""
    try:
        # Count receipt_items
        items_result = supabase.table("receipt_items").select("id", count="exact").eq("receipt_id", receipt_id).execute()
        items_count = items_result.count if items_result.count else 0
        
        # Count receipt_summaries
        summaries_result = supabase.table("receipt_summaries").select("id", count="exact").eq("receipt_id", receipt_id).execute()
        summaries_count = summaries_result.count if summaries_result.count else 0
        
        # Count receipt_processing_runs
        runs_result = supabase.table("receipt_processing_runs").select("id", count="exact").eq("receipt_id", receipt_id).execute()
        runs_count = runs_result.count if runs_result.count else 0
        
        return {
            'items': items_count,
            'summaries': summaries_count,
            'runs': runs_count
        }
    except Exception as e:
        print(f"⚠️  Error getting related data count: {e}")
        return {'items': 0, 'summaries': 0, 'runs': 0}


def delete_receipt_and_related_data(receipt_id: str, dry_run: bool = True) -> bool:
    """
    删除小票及所有关联数据
    
    Args:
        receipt_id: Receipt ID to delete
        dry_run: If True, only print what would be deleted
        
    Returns:
        True if successful (or would be successful in dry_run mode)
    """
    if dry_run:
        print(f"  [DRY RUN] Would delete receipt {receipt_id} and related data")
        return True
    
    try:
        # Delete in correct order (children first due to foreign key constraints)
        # 1. receipt_items
        supabase.table("receipt_items").delete().eq("receipt_id", receipt_id).execute()
        
        # 2. receipt_summaries
        supabase.table("receipt_summaries").delete().eq("receipt_id", receipt_id).execute()
        
        # 3. receipt_processing_runs
        supabase.table("receipt_processing_runs").delete().eq("receipt_id", receipt_id).execute()
        
        # 4. receipts (CASCADE should handle remaining references)
        supabase.table("receipts").delete().eq("id", receipt_id).execute()
        
        print(f"  ✅ Deleted receipt {receipt_id}")
        return True
    except Exception as e:
        print(f"  ❌ Error deleting receipt {receipt_id}: {e}")
        return False


def clean_duplicates(user_id: str = None, dry_run: bool = True):
    """
    清理重复小票
    
    Args:
        user_id: Optional user_id to filter by
        dry_run: If True, only print what would be deleted without actually deleting
    """
    print("\n" + "="*60)
    print("🧹 清理重复小票")
    print("="*60)
    
    if dry_run:
        print("⚠️  DRY RUN MODE - 不会实际删除数据")
    else:
        print("⚠️  LIVE MODE - 将实际删除数据！")
        response = input("\n确认要删除重复数据吗？输入 'YES' 继续: ")
        if response != "YES":
            print("❌ 操作已取消")
            return
    
    print()
    
    duplicates = find_duplicate_receipts(user_id)
    
    if not duplicates:
        print("✅ 没有发现重复的小票！")
        return
    
    print(f"\n📊 发现 {len(duplicates)} 组重复小票（共 {sum(d['count'] for d in duplicates)} 张小票）\n")
    
    total_to_delete = 0
    total_to_keep = 0
    
    for idx, dup_group in enumerate(duplicates, 1):
        file_hash = dup_group['file_hash']
        count = dup_group['count']
        receipts = dup_group['receipts']
        
        print(f"\n{'='*60}")
        print(f"重复组 #{idx}: {count} 张重复小票")
        print(f"file_hash: {file_hash[:20]}...")
        print(f"{'='*60}")
        
        # 保留最早上传的
        keep_receipt = receipts[0]
        delete_receipts = receipts[1:]
        
        print(f"\n✅ 保留:")
        print(f"  ID: {keep_receipt['id']}")
        print(f"  上传时间: {keep_receipt['uploaded_at']}")
        print(f"  状态: {keep_receipt['current_status']}")
        related = get_receipt_related_data_count(keep_receipt['id'])
        print(f"  关联数据: {related['items']} items, {related['summaries']} summaries, {related['runs']} runs")
        total_to_keep += 1
        
        print(f"\n❌ 删除 ({len(delete_receipts)} 张):")
        for receipt in delete_receipts:
            print(f"\n  ID: {receipt['id']}")
            print(f"  上传时间: {receipt['uploaded_at']}")
            print(f"  状态: {receipt['current_status']}")
            related = get_receipt_related_data_count(receipt['id'])
            print(f"  关联数据: {related['items']} items, {related['summaries']} summaries, {related['runs']} runs")
            
            success = delete_receipt_and_related_data(receipt['id'], dry_run=dry_run)
            if success:
                total_to_delete += 1
    
    print("\n" + "="*60)
    print("📊 清理总结")
    print("="*60)
    print(f"保留小票: {total_to_keep}")
    print(f"{'将删除' if dry_run else '已删除'}: {total_to_delete}")
    print()
    
    if dry_run:
        print("💡 这是 DRY RUN 模式，没有实际删除数据")
        print("💡 如果确认无误，请运行: python clean_duplicate_receipts.py")
    else:
        print("✅ 清理完成！")


def main():
    parser = argparse.ArgumentParser(description="清理重复的小票数据")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际删除数据")
    parser.add_argument("--user-id", type=str, help="只清理指定用户的重复数据")
    
    args = parser.parse_args()
    
    # Default to dry-run if not explicitly disabled
    dry_run = args.dry_run if '--dry-run' in sys.argv else (not any(arg in sys.argv for arg in ['--no-dry-run', '--live']))
    
    clean_duplicates(user_id=args.user_id, dry_run=dry_run)


if __name__ == "__main__":
    main()
