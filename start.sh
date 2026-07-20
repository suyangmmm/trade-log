#!/bin/bash
# 启动交易开仓流程记录服务器
# 用法: ./start.sh [port]

PORT=${1:-5800}
cd "$(dirname "$0")"

# 安装依赖
pip3 install -q flask pillow gunicorn 2>/dev/null

# 检查 gunicorn 是否可用
if command -v gunicorn &> /dev/null; then
    echo "Starting with gunicorn on port $PORT..."
    export TRADE_PORT=$PORT
    gunicorn -w 1 -b "0.0.0.0:$PORT" server:app
else
    echo "gunicorn not found, using Flask dev server..."
    export TRADE_PORT=$PORT
    python3 server.py
fi
