"""
weibo-follow 配置生成模块
"""
import copy
import os

from utils import now_local, save_runtime_config


DEFAULT_OUTPUT_DIRECTORY = "/app/data/weibo-follow"
DEFAULT_SQLITE_DB_PATH = os.path.join(os.environ.get("SQLITE_DATA_DIR", "/app/data/sqlite"), "weibo_follow.db")


def generate_config(params, global_cookie, mysql_config, mongo_config=None, sqlite_config=None, timestamp=None):
    """生成 weibo-follow 的唯一运行配置文件"""
    params = params or {}
    mongo_config = mongo_config or {}
    sqlite_config = sqlite_config or {}
    timestamp = timestamp or now_local()

    user_id_list = params.get("user_id_list", [])
    first_user_id = user_id_list[0] if user_id_list else "unknown"
    os.makedirs(DEFAULT_OUTPUT_DIRECTORY, exist_ok=True)
    output_filename = os.path.join(
        DEFAULT_OUTPUT_DIRECTORY,
        f"{first_user_id}_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_user_id_list.txt",
    )

    gui_params = copy.deepcopy(params)
    gui_params["output_filename"] = output_filename

    # 数据库输出开关
    use_sqlite = bool(params.get("use_sqlite", False))
    use_mysql = bool(params.get("use_mysql", False))
    use_mongo = bool(params.get("use_mongo", False))

    # SQLite 路径: 从全局 sqlite_config 获取
    sqlite_db_path = sqlite_config.get("db_path") or DEFAULT_SQLITE_DB_PATH
    os.makedirs(os.path.dirname(sqlite_db_path) or "/app/data/sqlite", exist_ok=True)

    # MongoDB URI: 从全局 mongo_config 获取，回退到环境变量
    mongodb_uri = mongo_config.get("uri") or os.environ.get("MONGODB_URI", "")
    gui_params["mongodb_uri"] = mongodb_uri

    config = {
        "user_id_list": user_id_list,
        # cookie 不再写入磁盘 JSON 文件，通过环境变量 WEIBO_COOKIE 传递
        "output_filename": output_filename,
        # 数据库配置
        "use_sqlite": use_sqlite,
        "use_mysql": use_mysql,
        "use_mongo": use_mongo,
        "sqlite_db_path": sqlite_db_path,
        "mongodb_URI": mongodb_uri,
        "mysql_config": mysql_config if use_mysql else {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "charset": "utf8mb4"
        },
        "_gui_params": gui_params,
    }

    _, config_path = save_runtime_config("weibo-follow", config, timestamp=timestamp)
    return config_path
