# 1. 基础镜像
FROM python:3.11-slim

# 2. 安装系统依赖（如果后面 Pillow / numpy 用得到）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. 设置工作目录（保持和原来一致，代码零侵入）
WORKDIR /app

# 4. 先复制依赖文件并安装（build context = 项目根目录）
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 5. 复制后端代码（保持原有结构：/app/app/main.py）
COPY backend/ /app/

# 6. 复制 content 目录（articles & updates for /api/blog）
#    main.py 用 Path(__file__).parent.parent.parent / "content"
#    即 /app/app/main.py -> parent.parent.parent = / -> /content
#    所以放在 /content
COPY content/ /content/

# 7. 让 uvicorn 在容器里监听 0.0.0.0:$PORT（Cloud Run 会注入 PORT）
ENV PYTHONUNBUFFERED=1

# 8. 默认使用 Cloud Run 约定的 8080 端口
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
