# -*- coding: utf-8 -*-
import sys
import io
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def test_aws_connection():
    """测试AWS连接和凭证"""
    try:
        # 测试凭证是否有效
        sts = boto3.client('sts', region_name='us-west-2')
        identity = sts.get_caller_identity()
        
        print("=" * 50)
        print("✅ AWS凭证配置成功！")
        print("=" * 50)
        print(f"账户ID: {identity['Account']}")
        print(f"用户ARN: {identity['Arn']}")
        print(f"用户ID: {identity['UserId']}")
        return True
        
    except NoCredentialsError:
        print("❌ 错误：未找到AWS凭证")
        return False
    except ClientError as e:
        print(f"❌ AWS错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False

def test_textract_simple():
    """测试Textract服务是否可用"""
    try:
        client = boto3.client('textract', region_name='us-west-2')
        
        # 创建一个简单的测试图片（1x1白色像素PNG）
        import base64
        test_image = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
        )
        
        response = client.detect_document_text(
            Document={'Bytes': test_image}
        )
        
        print("\n" + "=" * 50)
        print("✅ Textract API调用成功！")
        print("=" * 50)
        print(f"响应状态: 成功")
        print(f"检测到的块数量: {len(response.get('Blocks', []))}")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"\n❌ Textract API错误: {error_code}")
        print(f"错误信息: {e.response['Error']['Message']}")
        
        if error_code == 'AccessDeniedException':
            print("\n💡 提示：你的IAM用户可能没有Textract权限")
            print("   请确保在IAM中给用户添加了'AmazonTextractFullAccess'策略")
        
        return False
    except Exception as e:
        print(f"\n❌ 未知错误: {e}")
        return False

if __name__ == "__main__":
    print("开始测试AWS配置...\n")
    
    # 测试1：AWS凭证
    if test_aws_connection():
        # 测试2：Textract服务
        test_textract_simple()
    else:
        print("\n⚠️ 请先修复AWS凭证配置问题")
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("=" * 50)
