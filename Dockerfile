# ============================================================
# WeiboHarvester
# 整合 dataabc 的微博采集工具
# 支持环境变量配置 + MySQL 全局数据库 + GUI 管理后台
# ============================================================

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 创建程序目录
RUN mkdir -p \
    /app/data \
    /app/logs/gui-web \
    /app/logs/weibo-crawler \
    /app/logs/weibo-follow \
    /app/logs/weibo-search \
    /app/temp/gui-web/runtime-configs/weibo-crawler \
    /app/temp/gui-web/runtime-configs/weibo-follow \
    /app/temp/gui-web/runtime-configs/weibo-search \
    /app/config \
    /app/data/sqlite

# 安装构建工具（psutil 等需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- 依赖安装层（先于代码 COPY，利用 Docker 层缓存） ----
# 合并所有依赖文件
COPY requirements-all.txt /app/requirements-all.txt
COPY gui-web/requirements.txt /app/gui-web/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements-all.txt \
    && pip install --no-cache-dir -r /app/gui-web/requirements.txt

# ---- 代码层（放最后，只有代码变更时才重建此层） ----
# 复制爬虫程序代码
COPY tools/dataabc/weibo-crawler /app/weibo-crawler
COPY tools/dataabc/weibo-follow /app/weibo-follow
COPY tools/dataabc/weibo-search /app/weibo-search

# 复制 GUI 管理后台
COPY gui-web /app/gui-web

# 复制启动脚本
COPY start.py /app/
COPY menu.sh /app/
RUN chmod +x /app/menu.sh

# ---- 环境变量 ----
ENV PYTHONUNBUFFERED=1

# Flask 安全配置（生产环境必须通过 docker-compose 覆盖这些值）
ENV FLASK_SECRET_KEY=""
ENV API_TOKEN=""

# SQLite 配置
ENV SQLITE_DATA_DIR=/app/data/sqlite

# MongoDB 默认配置
ENV MONGODB_URI=mongodb://weibo-mongo:27017/

# MySQL 默认配置（密码必须通过 .env 或 docker-compose 环境变量注入）
ENV MYSQL_HOST=weibo-mysql
ENV MYSQL_PORT=3306
ENV MYSQL_USER=root
ENV MYSQL_PASSWORD=
ENV MYSQL_DATABASE=weibo_crawler

# 反封禁策略默认配置（平衡模式）
ENV ANTI_BAN_ENABLED=true
ENV MAX_WEIBO_PER_SESSION=500
ENV BATCH_SIZE=50
ENV BATCH_DELAY=30
ENV REQUEST_DELAY_MIN=8
ENV REQUEST_DELAY_MAX=15
ENV MAX_SESSION_TIME=600
ENV MAX_API_ERRORS=5
ENV REST_TIME_MIN=180

# 输出配置
ENV WRITE_MODE=csv,json
ENV OUTPUT_DIRECTORY=/app/data

# 日志配置
ENV LOG_LEVEL=INFO

# 默认命令 - 直接启动 GUI 服务，docker-compose 可直接复用
CMD ["python3", "/app/gui-web/app.py"]
