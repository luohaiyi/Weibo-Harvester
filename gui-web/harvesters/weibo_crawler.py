"""
weibo-crawler 配置生成模块
"""
import copy
import os

from utils import save_runtime_config


DEFAULT_OUTPUT_DIRECTORY = "/app/data/weibo-crawler"
DEFAULT_SQLITE_DB_PATH = os.path.join(os.environ.get("SQLITE_DATA_DIR", "/app/data/sqlite"), "weibodata.db")
LEGACY_OUTPUT_MARKERS = {"", ".", "./", "weibo", "weibo_data"}
LEGACY_SQLITE_MARKERS = {"", ".", "./", "weibodata.db"}


def _normalize_output_directory(value):
    raw = str(value or "").strip()
    if raw in LEGACY_OUTPUT_MARKERS:
        return DEFAULT_OUTPUT_DIRECTORY
    if os.path.isabs(raw):
        return raw
    return os.path.join(DEFAULT_OUTPUT_DIRECTORY, raw)


def _normalize_sqlite_db_path(value, output_directory):
    raw = str(value or "").strip()
    if raw in LEGACY_SQLITE_MARKERS:
        return os.path.join(output_directory, "weibodata.db")
    if os.path.isabs(raw):
        return raw
    return os.path.join(output_directory, raw)


def generate_config(params, global_cookie, mysql_config, mongo_config=None, sqlite_config=None, timestamp=None):
    """生成 weibo-crawler 的唯一运行配置文件"""
    params = params or {}
    mongo_config = mongo_config or {}
    sqlite_config = sqlite_config or {}
    gui_params = copy.deepcopy(params)
    write_mode = params.get("write_mode", [])
    if isinstance(write_mode, str):
        write_mode = [write_mode]

    output_directory = _normalize_output_directory(params.get("output_directory"))
    # Workaround: weibo.py 使用 + os.sep + 拼接路径，需转为相对于 /app/weibo-crawler 的相对路径
    if os.path.isabs(output_directory):
        output_directory = os.path.relpath(output_directory, "/app/weibo-crawler")
    sqlite_db_path = _normalize_sqlite_db_path(
        sqlite_config.get("db_path", DEFAULT_SQLITE_DB_PATH),
        output_directory
    )
    os.makedirs(output_directory, exist_ok=True)
    os.makedirs(os.path.dirname(sqlite_db_path), exist_ok=True)

    gui_params["output_directory"] = params.get("output_directory", "")
    gui_params["sqlite_db_path"] = sqlite_db_path

    # MongoDB URI: 从全局 mongo_config 获取
    mongodb_uri = mongo_config.get("uri", "")

    config = {
        "user_id_list": params.get("user_id_list", []),
        "only_crawl_original": params.get("only_crawl_original", 0),
        "query_list": params.get("query_list", []),
        "since_date": params.get("since_date", "2026-01-01"),
        "end_date": params.get("end_date", ""),
        "start_page": params.get("start_page", 1),
        "page_weibo_count": params.get("page_weibo_count", 20),
        "write_mode": write_mode or ["csv", "json", "markdown"],
        "markdown_split_by": params.get("markdown_split_by", "day_by_month"),
        "original_pic_download": params.get("original_pic_download", 0),
        "retweet_pic_download": params.get("retweet_pic_download", 0),
        "original_video_download": params.get("original_video_download", 0),
        "retweet_video_download": params.get("retweet_video_download", 0),
        "original_live_photo_download": params.get("original_live_photo_download", 0),
        "retweet_live_photo_download": params.get("retweet_live_photo_download", 0),
        "avatar_download": params.get("avatar_download", 0),
        "download_comment": params.get("download_comment", 0),
        "comment_max_download_count": params.get("comment_max_download_count", 100),
        "comment_pic_download": params.get("comment_pic_download", 0),
        "download_repost": params.get("download_repost", 0),
        "repost_max_download_count": params.get("repost_max_download_count", 100),
        "output_directory": output_directory,
        "user_id_as_folder_name": params.get("user_id_as_folder_name", 0),
        "remove_html_tag": params.get("remove_html_tag", 1),
        # cookie 不再写入磁盘 JSON 文件，通过环境变量 WEIBO_COOKIE 传递
        "sqlite_db_path": sqlite_db_path,
        "store_binary_in_sqlite": params.get("store_binary_in_sqlite", 0),
        "mongodb_URI": mongodb_uri,
        "write_time_in_exif": params.get("write_time_in_exif", 1),
        "change_file_time": params.get("change_file_time", 1),
        "post_config": params.get("post_config", {
            "api_url": "",
            "api_token": ""
        }),
        "anti_ban_config": params.get("anti_ban_config", {
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
        }),
        "mysql_config": mysql_config if "mysql" in write_mode else {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "charset": "utf8mb4"
        },
        "_gui_params": gui_params,
    }

    _, config_path = save_runtime_config("weibo-crawler", config, timestamp=timestamp)
    return config_path
