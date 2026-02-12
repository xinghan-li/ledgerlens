"""
启动 FastAPI 后端的便捷脚本。

如果端口 8000 被占用，自动切换到 8081-8084。
自动将端口信息写入文件供前端读取。

使用方法:
    python run_backend.py
"""
import uvicorn
import socket
import sys
import io
import json
from pathlib import Path

# Fix encoding issues on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def write_port_config(port: int):
    """将端口配置写入文件供前端读取。"""
    # 写入到项目根目录
    root_dir = Path(__file__).parent.parent
    config_file = root_dir / "backend-port.json"
    
    config = {
        "port": port,
        "url": f"http://localhost:{port}",
        "docs_url": f"http://localhost:{port}/docs"
    }
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✓ 端口配置已写入: {config_file}")
    except Exception as e:
        print(f"⚠ 警告: 无法写入端口配置文件: {e}")


def main():
    """启动 FastAPI 服务器。"""
    # 默认端口
    port = 8000
    
    # 如果端口 8000 被占用，依次尝试其他端口
    ports_to_try = [8000, 8081, 8082, 8083, 8084]
    port_found = False
    
    for test_port in ports_to_try:
        if not is_port_in_use(test_port):
            port = test_port
            port_found = True
            if test_port != 8000:
                print(f"端口 8000 已被占用，切换到端口 {port}")
            break
    
    if not port_found:
        print(f"错误: 端口 8000-8084 全部被占用，请手动关闭其他服务或指定其他端口")
        sys.exit(1)
    
    # 写入端口配置文件
    write_port_config(port)
    
    print(f"正在启动服务器: http://127.0.0.1:{port}")
    print(f"API 文档: http://127.0.0.1:{port}/docs")
    
    # 启动 uvicorn 服务器
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
