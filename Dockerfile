FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py ./
COPY trade-log.html ./

# 环境变量
ENV TRADE_PORT=5800
ENV TRADE_HOST=0.0.0.0
ENV TRADE_DEBUG=0
ENV TRADE_SECRET=change-me-in-production

EXPOSE 5800

CMD gunicorn -w 1 -b 0.0.0.0:5800 server:app
