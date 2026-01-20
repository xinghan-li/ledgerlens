"""
启动 FastAPI 后端的便捷脚本。

如果端口 8000 被占用，自动切换到 8081。

使用方法:
    python run_backend.py
"""
import uvicorn
import socket
import sys


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def main():
    """启动 FastAPI 服务器。"""
    # 默认端口
    port = 8000
    
    # 如果端口 8000 被占用，使用 8081
    if is_port_in_use(port):
        print(f"端口 {port} 已被占用，切换到端口 8081")
        port = 8081
        
        # 如果 8081 也被占用，报错退出
        if is_port_in_use(port):
            print(f"错误: 端口 {port} 也被占用，请手动指定其他端口")
            sys.exit(1)
    
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
