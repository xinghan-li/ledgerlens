# 1. 基础镜像
FROM python:3.11-slim

# 2. 安装系统依赖（如果后面 Pillow / numpy 用得到）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. 设置工作目录
WORKDIR /app

# 4. 先复制依赖文件并安装
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 5. 再复制代码
COPY . /app

# 6. 让 uvicorn 在容器里监听 0.0.0.0:$PORT（Cloud Run 会注入 PORT）
ENV PYTHONUNBUFFERED=1

# 7. 默认使用 Cloud Run 约定的 8080 端口
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
