"""
weibo-search 配置生成模块
生成 JSON 配置文件，由正式运行入口读取并启动 Scrapy
"""
import copy
import os

from utils import save_runtime_config


DEFAULT_OUTPUT_ROOT = "/app/data/weibo-search"
DEFAULT_IMAGES_STORE = os.path.join(DEFAULT_OUTPUT_ROOT, "images")
DEFAULT_FILES_STORE = os.path.join(DEFAULT_OUTPUT_ROOT, "files")
LEGACY_STORE_MARKERS = {"", ".", "./", "结果文件"}


def _normalize_store_path(value, default_path):
    raw = str(value or "").strip()
    if raw in LEGACY_STORE_MARKERS:
        return default_path
    if os.path.isabs(raw):
        return raw
    return os.path.join(DEFAULT_OUTPUT_ROOT, raw)


def generate_config(params, global_cookie, mysql_config, mongo_config=None, sqlite_config=None, timestamp=None):
    """生成 weibo-search 的唯一运行配置文件"""
    params = params or {}
    mongo_config = mongo_config or {}
    gui_params = copy.deepcopy(params)

    keyword = str(params.get("keyword", "")).strip() or "默认"
    keyword_list = [keyword]

    region_input = str(params.get("region", "全部")).strip() or "全部"
    if "," in region_input:
        region_list = [r.strip() for r in region_input.split(",") if r.strip()]
    else:
        region_list = [region_input]

    weibo_type = int(params.get("search_type", "1"))
    contain_type = int(params.get("filter_type", "0"))
    start_date = params.get("start_time", "")[:10] if params.get("start_time") else ""
    end_date = params.get("end_time", "")[:10] if params.get("end_time") else ""
    further_threshold = int(params.get("further_threshold", 46))
    limit_result = int(params.get("limit_result", 0))
    max_pages = int(params.get("max_pages", 100))
    download_delay = int(params.get("wait_time", 5))
    images_store = _normalize_store_path(params.get("images_store"), DEFAULT_IMAGES_STORE)
    files_store = _normalize_store_path(params.get("files_store"), DEFAULT_FILES_STORE)

    try:
        output_root = os.path.commonpath([images_store, files_store])
    except ValueError:
        output_root = DEFAULT_OUTPUT_ROOT
    if not output_root or output_root == os.sep:
        output_root = DEFAULT_OUTPUT_ROOT

    os.makedirs(output_root, exist_ok=True)
    os.makedirs(images_store, exist_ok=True)
    os.makedirs(files_store, exist_ok=True)

    gui_params["images_store"] = images_store
    gui_params["files_store"] = files_store

    use_csv = bool(params.get("use_csv", True))
    use_mysql = bool(params.get("use_mysql", False))
    use_mongo = bool(params.get("use_mongo", False))
    use_sqlite = bool(params.get("use_sqlite", False))
    use_images = bool(params.get("use_images", False))
    use_videos = bool(params.get("use_videos", False))

    config = {
        "KEYWORD_LIST": keyword_list,
        "WEIBO_TYPE": weibo_type,
        "CONTAIN_TYPE": contain_type,
        "REGION": region_list,
        "START_DATE": start_date,
        "END_DATE": end_date,
        "FURTHER_THRESHOLD": further_threshold,
        "LIMIT_RESULT": limit_result,
        "MAX_PAGES": max_pages,
        "DOWNLOAD_DELAY": download_delay,
        "OUTPUT_ROOT": output_root,
        "IMAGES_STORE": images_store,
        "FILES_STORE": files_store,
        # cookie 不再写入磁盘 JSON 文件，通过环境变量 WEIBO_COOKIE 传递
        # settings.py 会从环境变量 WEIBO_COOKIE 读取作为 fallback
        "LOG_LEVEL": "INFO",  # GUI 模式下显示详细日志，便于排查问题
        "use_csv": use_csv,
        "use_mysql": use_mysql,
        "use_mongo": use_mongo,
        "use_sqlite": use_sqlite,
        "use_images": use_images,
        "use_videos": use_videos,
        "_gui_params": gui_params,
    }

    if use_mysql:
        config["MYSQL_HOST"] = mysql_config.get("host", "localhost")
        config["MYSQL_PORT"] = mysql_config.get("port", 3306)
        config["MYSQL_USER"] = mysql_config.get("user", "root")
        config["MYSQL_PASSWORD"] = mysql_config.get("password", "")
        config["MYSQL_DATABASE"] = mysql_config.get("database", "weibo")

    if use_mongo:
        # MongoDB URI: 从全局 mongo_config 获取，回退到环境变量/默认值
        mongo_uri = mongo_config.get("uri") or os.environ.get("MONGODB_URI", "mongodb://weibo-mongo:27017/")
        config["MONGO_URI"] = mongo_uri

    _, config_path = save_runtime_config("weibo-search", config, timestamp=timestamp)
    return config_path
