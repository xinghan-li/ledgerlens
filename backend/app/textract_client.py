"""
AWS Textract 客户端，用于解析收据。

使用 AWS Textract 的 detect_document_text 和 analyze_expense API 来提取收据结构化信息。
"""
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from .config import settings
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Textract client instance
_client = None


def _get_client():
    """获取或创建 Textract 客户端。"""
    global _client
    if _client is None:
        try:
            # 从环境变量或默认配置获取 region
            region = getattr(settings, 'aws_region', 'us-west-2')
            _client = boto3.client('textract', region_name=region)
            logger.info(f"AWS Textract client initialized (region: {region})")
        except NoCredentialsError:
            raise ValueError(
                "AWS credentials not found. Please configure AWS credentials using:\n"
                "1. AWS credentials file (~/.aws/credentials)\n"
                "2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
                "3. IAM role (if running on EC2)"
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize AWS Textract client: {e}")
    
    return _client


def parse_receipt_textract(image_bytes: bytes) -> Dict[str, Any]:
    """
    使用 AWS Textract 解析收据图片。
    
    使用 detect_document_text API 提取文本，然后使用 analyze_expense API 提取结构化信息。
    
    Args:
        image_bytes: 图片文件字节
        
    Returns:
        解析后的收据数据字典，格式与 Document AI 类似：
        {
            "raw_text": str,
            "entities": {
                "supplier_name": {"value": str, "confidence": float},
                "total_amount": {"value": str, "confidence": float},
                ...
            },
            "line_items": [
                {
                    "raw_text": str,
                    "product_name": str,
                    "line_total": float,
                    ...
                }
            ],
            "merchant_name": str,
            ...
        }
    """
    client = _get_client()
    
    try:
        # Step 1: 使用 detect_document_text 提取原始文本
        logger.info("Calling Textract detect_document_text...")
        text_response = client.detect_document_text(
            Document={'Bytes': image_bytes}
        )
        
        # 提取所有文本块
        raw_text_lines = []
        blocks = text_response.get('Blocks', [])
        for block in blocks:
            if block.get('BlockType') == 'LINE':
                text = block.get('Text', '')
                if text:
                    raw_text_lines.append(text)
        
        raw_text = '\n'.join(raw_text_lines)
        logger.info(f"Extracted {len(raw_text_lines)} text lines from Textract")
        
        # Step 2: 使用 analyze_expense 提取结构化信息（如果可用）
        entities = {}
        line_items = []
        merchant_name = None
        
        try:
            logger.info("Calling Textract analyze_expense...")
            expense_response = client.analyze_expense(
                Document={'Bytes': image_bytes}
            )
            
            # 提取 expense 字段
            expense_documents = expense_response.get('ExpenseDocuments', [])
            if expense_documents:
                expense_doc = expense_documents[0]
                
                # 提取供应商信息
                summary_fields = expense_doc.get('SummaryFields', [])
                for field in summary_fields:
                    field_type = field.get('Type', {}).get('Text', '').lower()
                    field_value = field.get('ValueDetection', {}).get('Text', '')
                    confidence = field.get('ValueDetection', {}).get('Confidence', 0.0) / 100.0
                    
                    if field_type == 'vendor_name' or field_type == 'merchant_name':
                        merchant_name = field_value
                        entities['supplier_name'] = {
                            'value': field_value,
                            'confidence': confidence
                        }
                    elif field_type == 'total' or field_type == 'total_amount':
                        entities['total_amount'] = {
                            'value': field_value,
                            'confidence': confidence
                        }
                    elif field_type == 'receipt_date' or field_type == 'invoice_date':
                        entities['receipt_date'] = {
                            'value': field_value,
                            'confidence': confidence
                        }
                    elif field_type == 'tax':
                        entities['total_tax_amount'] = {
                            'value': field_value,
                            'confidence': confidence
                        }
                
                # 提取 line items
                line_item_groups = expense_doc.get('LineItemGroups', [])
                for group in line_item_groups:
                    line_items_list = group.get('LineItems', [])
                    for item in line_items_list:
                        item_data = {
                            'raw_text': '',
                            'product_name': None,
                            'quantity': None,
                            'unit': None,
                            'unit_price': None,
                            'line_total': None,
                            'is_on_sale': False,
                            'category': None
                        }
                        
                        # 提取商品信息
                        for field in item.get('LineItemExpenseFields', []):
                            field_type = field.get('Type', {}).get('Text', '').lower()
                            field_value = field.get('ValueDetection', {}).get('Text', '')
                            
                            if field_type == 'item' or field_type == 'product_name':
                                item_data['product_name'] = field_value
                                item_data['raw_text'] = field_value
                            elif field_type == 'quantity':
                                try:
                                    item_data['quantity'] = float(field_value)
                                except (ValueError, TypeError):
                                    pass
                            elif field_type == 'unit_price' or field_type == 'price':
                                try:
                                    item_data['unit_price'] = float(field_value.replace('$', '').replace(',', ''))
                                except (ValueError, TypeError):
                                    pass
                            elif field_type == 'amount' or field_type == 'line_total':
                                try:
                                    item_data['line_total'] = float(field_value.replace('$', '').replace(',', ''))
                                except (ValueError, TypeError):
                                    pass
                        
                        if item_data['product_name'] or item_data['line_total']:
                            line_items.append(item_data)
            
            logger.info(f"Extracted {len(line_items)} line items from Textract analyze_expense")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDeniedException':
                logger.warning("Textract analyze_expense not available (missing permissions). Using detect_document_text only.")
            else:
                logger.warning(f"Textract analyze_expense failed: {error_code}. Using detect_document_text only.")
        
        # 如果没有从 analyze_expense 获取 merchant_name，尝试从 raw_text 中提取
        if not merchant_name:
            # 简单的启发式方法：取前几行作为可能的商户名
            lines = raw_text.split('\n')
            for line in lines[:5]:
                line = line.strip()
                if line and len(line) > 3 and len(line) < 50:
                    # 跳过明显不是商户名的行
                    if not any(skip in line.upper() for skip in ['TOTAL', 'DATE', 'TIME', 'REFERENCE', 'TRANS:', 'TERMINAL:']):
                        merchant_name = line
                        break
        
        # 构建返回结果（格式与 Document AI 类似，但添加 metadata）
        result = {
            'raw_text': raw_text,
            'entities': entities,
            'line_items': line_items,
            'merchant_name': merchant_name,
            'metadata': {
                'ocr_provider': 'aws_textract'
            }
        }
        
        # 添加其他字段（如果从 analyze_expense 获取到）
        if 'total_amount' in entities:
            try:
                result['total'] = float(entities['total_amount']['value'].replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                pass
        
        if 'receipt_date' in entities:
            result['purchase_date'] = entities['receipt_date']['value']
        
        logger.info(f"Textract parsing completed. Merchant: {merchant_name}, Items: {len(line_items)}")
        return result
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"Textract API error: {error_code} - {error_message}")
        raise ValueError(f"Textract API error: {error_code} - {error_message}")
    except Exception as e:
        logger.error(f"Textract parsing failed: {e}", exc_info=True)
        raise ValueError(f"Textract parsing failed: {str(e)}")
