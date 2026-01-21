"""
FastAPI application for Receipt OCR MVP.

Run instructions:
1. Create virtual environment:
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\\Scripts\\activate

2. Install dependencies:
   pip install -r requirements.txt

3. Copy and configure environment:
   cp .env.example .env
   # Edit .env with your actual values

4. Run server:
   uvicorn app.main:app --reload --port 8000

Example curl request:
curl -X POST "http://127.0.0.1:8000/api/receipts/ocr" \
  -F "file=@/path/to/receipt.jpg"
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .vision_client import ocr_document_bytes
from .supabase_client import save_receipt_ocr, save_parsed_receipt, get_or_create_merchant, get_test_user_id
from .models import ReceiptOCRResponse, ReceiptIngestRequest, ReceiptIngestResponse, ReceiptItemResponse
from .receipt_parser import parse_receipt
from .documentai_client import parse_receipt_documentai
from .textract_client import parse_receipt_textract
from .receipt_llm_processor import process_receipt_with_llm_from_docai, process_receipt_with_llm_from_ocr
from .workflow_processor import process_receipt_workflow
from .models import DocumentAIResultRequest
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Receipt OCR MVP",
    description="Minimal FastAPI backend for receipt OCR using Google Cloud Vision",
    version="1.0.0"
)

# Allow localhost frontends during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/receipt/goog-ocr", response_model=ReceiptOCRResponse)
async def ocr_receipt_google_vision(file: UploadFile = File(...)):
    """
    使用 Google Cloud Vision API 进行 OCR。
    
    - 接受 JPEG 或 PNG 图片
    - 最大文件大小：约 5MB
    - 返回提取的文本并保存到 Supabase
    """
    # Basic validation: only allow jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # Check file size (approximately 5MB limit)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # Perform OCR
        text = ocr_document_bytes(contents)
        logger.info(f"OCR completed for file: {file.filename}")
    except Exception as e:
        logger.error(f"OCR failed for {file.filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR failed: {str(e)}"
        )
    
    # Save to Supabase
    try:
        # TODO: wire user_id from auth later; use None for now
        saved = save_receipt_ocr(user_id=None, filename=file.filename, text=text)
        logger.info(f"Receipt saved to Supabase: {saved.get('id')}")
    except Exception as e:
        logger.error(f"Failed to save receipt to Supabase: {e}")
        # Still return the OCR result even if save fails
        return ReceiptOCRResponse(
            id=None,
            filename=file.filename,
            text=text,
        )
    
    return ReceiptOCRResponse(
        id=str(saved.get("id")) if saved.get("id") else None,
        filename=file.filename,
        text=text,
    )


@app.post("/api/ingest/receipt", response_model=ReceiptIngestResponse)
async def ingest_receipt(request: ReceiptIngestRequest):
    """
    接收 OCR 文本，解析收据信息并保存到数据库。
    
    - 解析商户名称、日期时间、总金额、商品项等
    - 保存到 receipts 和 receipt_items 表
    - 返回解析后的结构化数据
    
    注意：需要一个有效的 user_id（必须在 auth.users 表中存在）。
    可以通过以下方式提供：
    1. 从请求头中的认证信息获取（推荐，待实现）
    2. 设置 TEST_USER_ID 环境变量用于开发测试
    """
    # 获取用户 ID
    user_id = get_test_user_id()
    
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "user_id is required. Please either:\n"
                "1. Implement authentication to get user_id from request\n"
                "2. Set TEST_USER_ID environment variable (must exist in auth.users table)\n"
                "To create a test user, use Supabase Auth API or create one in Supabase dashboard."
            )
        )
    
    try:
        # 解析收据
        parsed = parse_receipt(request.text)
        
        # 如果识别到商户，获取或创建 merchant 记录
        if parsed.merchant_name:
            merchant_id = get_or_create_merchant(parsed.merchant_name)
            parsed.merchant_id = merchant_id
            logger.info(f"Merchant: {parsed.merchant_name} (ID: {merchant_id})")
        
        # 保存到数据库
        saved = save_parsed_receipt(
            user_id=user_id,
            parsed_receipt=parsed,
            ocr_text=request.text,
            image_url=None
        )
        
        receipt_id = saved["receipt_id"]
        logger.info(f"Receipt ingested successfully: ID={receipt_id}, Items={len(saved['items'])}")
        
        # 构建响应 - 从原始解析中获取 is_on_sale 信息
        items_response = []
        for idx, db_item in enumerate(saved["items"]):
            # 从原始解析的商品列表中查找对应的商品
            original_item = None
            if idx < len(parsed.items):
                original_item = parsed.items[idx]
            
            normalized_text = db_item.get("normalized_text") or db_item.get("raw_text", "")
            # 检查是否包含 [SALE] 标记
            is_on_sale = "[SALE]" in normalized_text or (original_item and original_item.is_on_sale)
            # 移除 [SALE] 标记以获取纯商品名
            product_name = normalized_text.replace("[SALE] ", "").strip() if normalized_text else ""
            
            items_response.append(
                ReceiptItemResponse(
                    id=db_item.get("id"),
                    line_index=db_item["line_index"],
                    product_name=product_name,
                    quantity=db_item.get("quantity"),
                    unit=None,  # 数据库中暂时没有单独存储 unit
                    unit_price=db_item.get("unit_price"),
                    line_total=db_item.get("line_total"),
                    is_on_sale=is_on_sale,
                    category=original_item.category if original_item else None,
                )
            )
        
        return ReceiptIngestResponse(
            receipt_id=receipt_id,
            merchant_name=parsed.merchant_name,
            merchant_id=parsed.merchant_id,
            purchase_time=parsed.purchase_time,
            total=float(parsed.total) if parsed.total else None,
            subtotal=float(parsed.subtotal) if parsed.subtotal else None,
            tax=float(parsed.tax) if parsed.tax else None,
            item_count=parsed.item_count,
            payment_method=parsed.payment_method,
            items=items_response,
        )
        
    except Exception as e:
        logger.error(f"Failed to ingest receipt: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Receipt ingestion failed: {str(e)}"
        )


@app.post("/api/receipt/goog-ocr-dai")
async def parse_receipt_with_documentai(file: UploadFile = File(...)):
    """
    使用 Google Document AI Expense Parser 解析收据图片。
    
    - 接受 JPEG 或 PNG 图片
    - 使用 Google Document AI 的 Expense Parser processor
    - 返回 Document AI 提取的结构化数据
    
    注意：此端点只返回解析结果，不保存到数据库。
    """
    # 基本验证：只允许 jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # 检查文件大小（约 5MB 限制）
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # 确定 MIME 类型
        mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
        
        # 使用 Document AI 解析
        parsed_data = parse_receipt_documentai(contents, mime_type=mime_type)
        logger.info(f"Document AI parsing completed for file: {file.filename}")
        
        return {
            "filename": file.filename,
            "success": True,
            "data": parsed_data
        }
        
    except Exception as e:
        logger.error(f"Document AI parsing failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Document AI parsing failed: {str(e)}"
        )


@app.post("/api/receipt/amzn-ocr")
async def parse_receipt_with_textract(file: UploadFile = File(...)):
    """
    使用 AWS Textract 解析收据图片。
    
    - 接受 JPEG 或 PNG 图片
    - 使用 AWS Textract 的 detect_document_text 和 analyze_expense API
    - 返回 Textract 提取的结构化数据（标准化格式，与 Document AI 兼容）
    
    注意：此端点只返回解析结果，不保存到数据库。
    返回的格式已经标准化，可以直接用于 /api/receipt/llm-process 端点。
    
    配置要求：
    - 需要配置 AWS 凭证（通过 ~/.aws/credentials 或环境变量）
    - 需要 IAM 权限：AmazonTextractFullAccess 或至少 detect_document_text 和 analyze_expense 权限
    """
    # 基本验证：只允许 jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # 检查文件大小（约 5MB 限制）
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # 使用 Textract 解析
        parsed_data = parse_receipt_textract(contents)
        logger.info(f"Textract parsing completed for file: {file.filename}")
        
        return {
            "filename": file.filename,
            "success": True,
            "data": parsed_data
        }
        
    except Exception as e:
        logger.error(f"Textract parsing failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Textract parsing failed: {str(e)}"
        )


@app.post("/api/receipt/openai-llm")
async def process_receipt_with_openai_llm_endpoint(request: DocumentAIResultRequest):
    """
    使用 OpenAI LLM 处理 OCR 结果（支持多个 OCR 提供商）。
    
    输入：任何 OCR 服务返回的 JSON（来自 /api/receipt/goog-ocr-dai 或 /api/receipt/amzn-ocr）
    
    核心优势（统一处理）：
    - 自动标准化不同 OCR 的输出格式
    - 基于 raw_text 的统一提取（不依赖 OCR 特定格式）
    - 统一的验证逻辑（不管 OCR 来源）
    - 商店特定的规则只需一套（针对 raw_text，不针对 OCR）
    
    流程：
    1. 自动检测并标准化 OCR 结果（Google Document AI / AWS Textract）
    2. 提取高置信度字段（confidence >= 0.95）作为 trusted_hints
    3. 根据商店名称获取对应的 RAG prompt
    4. 调用 OpenAI LLM 进行结构化重建
    5. 基于 raw_text 的后端数学验证（不依赖 OCR）
    6. 返回结构化的 JSON，可以直接存储到数据库
    
    注意：此端点返回完整的结构化数据，包括 tbd（待确认）字段。
    
    使用示例：
    1. 先调用 POST /api/receipt/goog-ocr-dai 或 POST /api/receipt/amzn-ocr 上传图片，获取 OCR 结果
    2. 将返回的 JSON 中的 data 字段作为 body 的 data 发送到此端点
    """
    try:
        # 检测 OCR 提供商（通过 metadata 或自动检测）
        ocr_data = request.data
        ocr_provider = "unknown"
        
        if isinstance(ocr_data, dict):
            # 检查是否有 metadata 字段
            if "metadata" in ocr_data and "ocr_provider" in ocr_data["metadata"]:
                ocr_provider = ocr_data["metadata"]["ocr_provider"]
            else:
                # 自动检测：检查是否有特征字段
                # 使用键检查而不是字符串转换，更高效且准确
                if "ExpenseDocuments" in ocr_data and isinstance(ocr_data.get("ExpenseDocuments"), list):
                    ocr_provider = "aws_textract"
                elif "entities" in ocr_data and "line_items" in ocr_data:
                    ocr_provider = "google_documentai"
                elif "Blocks" in ocr_data and isinstance(ocr_data.get("Blocks"), list):
                    # AWS Textract 的 detect_document_text 返回 Blocks
                    ocr_provider = "aws_textract"
        
        # 调用统一的 LLM 处理流程（自动标准化，使用 OpenAI）
        result = await process_receipt_with_llm_from_ocr(
            ocr_result=ocr_data,
            merchant_name=None,  # 从 OCR 结果中自动识别
            ocr_provider=ocr_provider,
            llm_provider="openai"
        )
        
        logger.info(f"OpenAI LLM processing completed for file: {request.filename} (OCR: {ocr_provider})")
        
        return {
            "filename": request.filename,
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"OpenAI LLM processing failed for {request.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI LLM processing failed: {str(e)}"
        )


@app.post("/api/receipt/gemini-llm")
async def process_receipt_with_gemini_llm_endpoint(request: DocumentAIResultRequest):
    """
    使用 Google Gemini LLM 处理 OCR 结果（支持多个 OCR 提供商）。
    
    输入：任何 OCR 服务返回的 JSON（来自 /api/receipt/goog-ocr-dai 或 /api/receipt/amzn-ocr）
    
    核心优势（统一处理）：
    - 自动标准化不同 OCR 的输出格式
    - 基于 raw_text 的统一提取（不依赖 OCR 特定格式）
    - 统一的验证逻辑（不管 OCR 来源）
    - 商店特定的规则只需一套（针对 raw_text，不针对 OCR）
    - 使用 Google Gemini LLM（暂时沿用 OpenAI 的 RAG prompt）
    
    流程：
    1. 自动检测并标准化 OCR 结果（Google Document AI / AWS Textract）
    2. 提取高置信度字段（confidence >= 0.95）作为 trusted_hints
    3. 根据商店名称获取对应的 RAG prompt（沿用 OpenAI 的 prompt）
    4. 调用 Google Gemini LLM 进行结构化重建
    5. 基于 raw_text 的后端数学验证（不依赖 OCR）
    6. 返回结构化的 JSON，可以直接存储到数据库
    
    注意：此端点返回完整的结构化数据，包括 tbd（待确认）字段。
    
    使用示例：
    1. 先调用 POST /api/receipt/goog-ocr-dai 或 POST /api/receipt/amzn-ocr 上传图片，获取 OCR 结果
    2. 将返回的 JSON 中的 data 字段作为 body 的 data 发送到此端点
    """
    try:
        # 检测 OCR 提供商（通过 metadata 或自动检测）
        ocr_data = request.data
        ocr_provider = "unknown"
        
        if isinstance(ocr_data, dict):
            # 检查是否有 metadata 字段
            if "metadata" in ocr_data and "ocr_provider" in ocr_data["metadata"]:
                ocr_provider = ocr_data["metadata"]["ocr_provider"]
            else:
                # 自动检测：检查是否有特征字段
                # 使用键检查而不是字符串转换，更高效且准确
                if "ExpenseDocuments" in ocr_data and isinstance(ocr_data.get("ExpenseDocuments"), list):
                    ocr_provider = "aws_textract"
                elif "entities" in ocr_data and "line_items" in ocr_data:
                    ocr_provider = "google_documentai"
                elif "Blocks" in ocr_data and isinstance(ocr_data.get("Blocks"), list):
                    # AWS Textract 的 detect_document_text 返回 Blocks
                    ocr_provider = "aws_textract"
        
        # 调用统一的 LLM 处理流程（自动标准化，使用 Gemini）
        result = await process_receipt_with_llm_from_ocr(
            ocr_result=ocr_data,
            merchant_name=None,  # 从 OCR 结果中自动识别
            ocr_provider=ocr_provider,
            llm_provider="gemini"
        )
        
        logger.info(f"Gemini LLM processing completed for file: {request.filename} (OCR: {ocr_provider})")
        
        return {
            "filename": request.filename,
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Gemini LLM processing failed for {request.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Gemini LLM processing failed: {str(e)}"
        )


@app.post("/api/receipt/workflow")
async def process_receipt_workflow_endpoint(file: UploadFile = File(...)):
    """
    完整的收据处理流程（workflow）。
    
    流程：
    1. Google Document AI OCR
    2. 根据 Gemini 限流决定使用 Gemini 还是 GPT-4o-mini
    3. LLM 处理得到结构化 JSON
    4. Sum check（容忍度 ±0.03）
    5. 如果失败，引入 AWS OCR + GPT-4o-mini 二次处理
    6. 文件存储和时间线记录
    7. 统计更新
    
    返回：
    - success: 是否成功
    - receipt_id: 收据 ID（格式：001_mmyydd_hhmm）
    - status: 状态（passed, passed_with_resolution, passed_after_backup, needs_manual_review, error）
    - data: 结构化的收据数据
    - sum_check: sum check 详情
    - timeline: 时间线（可选）
    """
    # 基本验证
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # 检查文件大小（约 5MB 限制）
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # 确定 MIME 类型
        mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
        
        # 调用 workflow 处理器
        result = await process_receipt_workflow(
            image_bytes=contents,
            filename=file.filename,
            mime_type=mime_type
        )
        
        logger.info(f"Workflow completed for {file.filename}: status={result.get('status')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Workflow failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Workflow processing failed: {str(e)}"
        )
