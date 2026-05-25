"""
GUI Web 配置文件
"""
import os


# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

# 爬虫路径（容器内路径）
CRAWLER_PATHS = {
    'weibo-crawler': '/app/weibo-crawler',
    'weibo-follow': '/app/weibo-follow',
    'weibo-search': '/app/weibo-search',
}

# 运行时目录（容器内路径，映射到宿主机 ./logs、./temp）
LOGS_DIR = '/app/logs'
TEMP_DIR = '/app/temp/gui-web'
GUI_LOGS_DIR = os.path.join(LOGS_DIR, 'gui-web')
LOG_CATEGORY_DIRS = {
    'gui-web': GUI_LOGS_DIR,
    'weibo-crawler': os.path.join(LOGS_DIR, 'weibo-crawler'),
    'weibo-follow': os.path.join(LOGS_DIR, 'weibo-follow'),
    'weibo-search': os.path.join(LOGS_DIR, 'weibo-search'),
}

# 数据文件路径
SETTINGS_FILE = os.path.join(TEMP_DIR, 'settings.json')
STATUS_FILE = os.path.join(TEMP_DIR, 'status.json')
HISTORY_FILE = os.path.join(TEMP_DIR, 'history.json')
RUNTIME_CONFIGS_DIR = os.path.join(TEMP_DIR, 'runtime-configs')
RUNTIME_CONFIG_PATHS = {
    crawler_type: os.path.join(RUNTIME_CONFIGS_DIR, crawler_type)
    for crawler_type in CRAWLER_PATHS
}


# ==================== 初始化辅助函数 ====================

def ensure_logs_dir(log_key=None):
    """确保日志目录存在"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    if log_key:
        target_dir = LOG_CATEGORY_DIRS.get(log_key)
        if not target_dir:
            raise KeyError(f'未知的日志目录类型: {log_key}')
        os.makedirs(target_dir, exist_ok=True)
        return target_dir

    for target_dir in LOG_CATEGORY_DIRS.values():
        os.makedirs(target_dir, exist_ok=True)
    return LOGS_DIR


def ensure_temp_dir():
    """确保 GUI 临时目录存在"""
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(RUNTIME_CONFIGS_DIR, exist_ok=True)
    for target_dir in RUNTIME_CONFIG_PATHS.values():
        os.makedirs(target_dir, exist_ok=True)
    return TEMP_DIR

# Flask 配置（可通过 .env 环境变量覆盖）
FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.environ.get('FLASK_PORT', '5100'))
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'

# 默认配置
DEFAULT_SETTINGS = {
    "version": "1.0",
    "cookie": "",
    "timezone": "Asia/Shanghai",  # 默认时区
    "mysql_config": {
        "enabled": False,
        "default_enabled": False,
        "host": os.environ.get("MYSQL_HOST", "weibo-mysql"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "weibo_harvester"),
        "charset": "utf8mb4"
    },
    "mongo_config": {
        "enabled": False,
        "default_enabled": False,
        "uri": os.environ.get("MONGODB_URI", "mongodb://weibo-mongo:27017/")
    },
    "sqlite_config": {
        "enabled": False,
        "default_enabled": False,
        "db_path": os.path.join(os.environ.get("SQLITE_DATA_DIR", "/app/data/sqlite"), "weibodata.db")
    },
    "log_settings": {
        "level": "INFO",
        "max_keep": 100,
        "log_retention_lines": 100,
        "log_file_max_size": 10,
        "log_file_backup_count": 5
    },
    "crawler_defaults": {
        "weibo-crawler": {
            "user_id_list": [],
            "only_crawl_original": 0,
            "since_date": "2026-01-01",
            "end_date": "",
            "write_mode": ["csv", "json", "markdown"],
            "original_pic_download": 0,
            "original_video_download": 0,
            "original_live_photo_download": 0,
            "retweet_pic_download": 0,
            "retweet_video_download": 0,
            "retweet_live_photo_download": 0,
            "download_comment": 0,
            "comment_max_download_count": 100,
            "comment_pic_download": 0,
            "download_repost": 0,
            "repost_max_download_count": 100,
            "start_page": 1,
            "page_weibo_count": 20,
            "remove_html_tag": 1,
            "user_id_as_folder_name": 0,
            "output_directory": "/app/data/weibo-crawler",
            "markdown_split_by": "day_by_month",
            "sqlite_db_path": "/app/data/sqlite/weibodata.db",
            "store_binary_in_sqlite": 0,
            "mongodb_URI": "mongodb://weibo-mongo:27017/",
            "write_time_in_exif": 1,
            "change_file_time": 1,
            "anti_ban_config": {
                "enabled": True,
                "max_weibo_per_session": 500,
                "batch_size": 50,
                "batch_delay": 30,
                "request_delay_min": 8,
                "request_delay_max": 15,
                "max_session_time": 600,
                "max_api_errors": 5,
                "rest_time_min": 180,
                "random_rest_probability": 0.01
            }
        },
        "weibo-follow": {
            "user_id_list": []
        },
        "weibo-search": {
            "KEYWORD_LIST": ["迪丽热巴"],
            "START_DATE": "2020-03-01",
            "END_DATE": "2020-03-01",
            "WEIBO_TYPE": 1,
            "CONTAIN_TYPE": 0,
            "REGION": ["全部"],
            "FURTHER_THRESHOLD": 46,
            "DOWNLOAD_DELAY": 10,
            "LIMIT_RESULT": 0,
            "OUTPUT_ROOT": "/app/data/weibo-search",
            "IMAGES_STORE": "/app/data/weibo-search/images",
            "FILES_STORE": "/app/data/weibo-search/files"
        }
    },
    "ui_state": {
        "history_filter": {
            "crawler_type": "all",
            "status": "all",
            "page_size": 20,
            "sort_order": "desc"
        }
    }
}

# 爬虫执行命令
# 所有模块统一通过 run.py 包装入口 + --config 参数启动
CRAWLER_COMMANDS = {
    'weibo-crawler': {
        'cmd': ['/usr/local/bin/python3', 'run.py'],
        'cwd_key': 'weibo-crawler',
    },
    'weibo-follow': {
        'cmd': ['/usr/local/bin/python3', 'run.py'],
        'cwd_key': 'weibo-follow',
    },
    'weibo-search': {
        'cmd': ['/usr/local/bin/python3', 'run.py'],
        'cwd_key': 'weibo-search',
    }
}

# 爬虫类型标识映射（用于日志文件名）
CRAWLER_NAME_MAP = {
    'weibo-crawler': 'crawler',
    'weibo-follow': 'follow',
    'weibo-search': 'search'
}


def get_log_filename(crawler_type, timestamp=None):
    """生成日志文件名，格式：crawler_2026-04-04_16-02-13.log"""
    if timestamp is None:
        # 使用无时区的当前时间
        from datetime import datetime
        timestamp = datetime.now()
    elif hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
        # 如果时间戳有时区信息，转换为本地时间并去掉时区信息
        timestamp = timestamp.replace(tzinfo=None)
    
    # 提取爬虫类型简称
    crawler_short = CRAWLER_NAME_MAP.get(crawler_type, crawler_type.replace('weibo-', ''))
    
    # 格式：crawler_2026-04-04_16-02-13.log
    filename = f"{crawler_short}_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.log"
    return filename


def get_log_directory(log_key=None):
    """获取日志目录；不传时返回日志根目录"""
    if log_key:
        return ensure_logs_dir(log_key)
    ensure_logs_dir()
    return LOGS_DIR


def get_log_file_path(crawler_type, timestamp=None):
    """获取日志文件完整路径"""
    filename = get_log_filename(crawler_type, timestamp)
    log_dir = get_log_directory(crawler_type)
    return os.path.join(log_dir, filename)
