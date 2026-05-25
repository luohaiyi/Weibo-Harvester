"""
Flask 后端 API
"""
import json
import os
import re
import sys
import subprocess
import signal
import time
import atexit
import logging
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests
from dotenv import load_dotenv

# 加载 .env 文件（项目根目录），在导入 config 之前完成
# 优先加载当前目录的 .env，其次加载父目录（项目根）的 .env
_env_path = Path(__file__).resolve().parent.parent / '.env'
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # fallback: 尝试默认路径

from flask import Flask, send_file, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('gui-web')

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, CRAWLER_PATHS, CRAWLER_COMMANDS, LOGS_DIR, CRAWLER_NAME_MAP
from config import ensure_temp_dir as _ensure_app_dirs  # 重命名避免与 utils 中冲突

# 应用启动时确保运行时目录存在（logs、temp）
_ensure_app_dirs()

from utils import (
    load_settings, save_settings, load_status, save_status,
    load_history, save_history,
    add_history_record, update_history_record, format_time_display,
    generate_output_summary, read_log_tail, read_log_file, clear_log_file,
    list_all_logs, clear_all_logs as clear_all_log_files, delete_log_file, get_log_file_path,
    get_history_record, summarize_failure_from_log,
    now_local, to_local_time,
    load_runtime_config, delete_runtime_config,
)
from harvesters.weibo_crawler import generate_config as generate_weibo_crawler_config
from harvesters.weibo_follow import generate_config as generate_weibo_follow_config
from harvesters.weibo_search import generate_config as generate_weibo_search_config

app = Flask(__name__)

# 修改 Jinja2 模板语法，避免与 Vue 冲突
app.jinja_env.variable_start_string = '{%{'
app.jinja_env.variable_end_string = '%}'
# SECRET_KEY 从环境变量读取，未设置则用随机密钥
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ---- 全局状态（受 state_lock 保护） ----
# 使用 dict 按 crawler_type 管理，支持三种爬虫各一个同时运行
_SENTINEL = object()  # 哨兵值，用于 _set_state 区分「未传参」和「传 None」
state_lock = threading.Lock()
running_processes = {}     # {crawler_type: subprocess.Popen}
running_history_ids = {}   # {crawler_type: str}
monitor_threads = {}       # {crawler_type: threading.Thread}

# ---- SocketIO 日志订阅管理（修复无限泄漏） ----
# key: client sid, value: stop_event (threading.Event)
_log_subscriptions = {}
_subscriptions_lock = threading.Lock()

# ---- 进程超时配置 ----
MAX_CRAWLER_RUNTIME_SECONDS = int(os.environ.get('MAX_CRAWLER_RUNTIME', '86400'))  # 默认 24 小时

# ---- API 认证 ----
API_TOKEN = os.environ.get('API_TOKEN', '').strip()


def require_auth(f):
    """API Token 认证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_TOKEN:
            return f(*args, **kwargs)
        token = request.headers.get('X-API-Token', '') or request.args.get('token', '')
        if token != API_TOKEN:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


def _get_state_snapshot():
    """获取全局状态快照（线程安全）"""
    with state_lock:
        return {
            'running_processes': dict(running_processes),
            'running_history_ids': dict(running_history_ids),
            'monitor_threads': dict(monitor_threads),
        }


def _set_crawler_state(crawler_type, process=_SENTINEL, history_id=_SENTINEL, monitor=_SENTINEL):
    """设置指定爬虫类型的状态（线程安全）。使用哨兵值区分「显式传 None」和「不传参」，避免意外覆盖。"""
    global running_processes, running_history_ids, monitor_threads
    with state_lock:
        if process is not _SENTINEL:
            if process is None:
                running_processes.pop(crawler_type, None)
            else:
                running_processes[crawler_type] = process
        if history_id is not _SENTINEL:
            if history_id is None:
                running_history_ids.pop(crawler_type, None)
            else:
                running_history_ids[crawler_type] = history_id
        if monitor is not _SENTINEL:
            if monitor is None:
                monitor_threads.pop(crawler_type, None)
            else:
                monitor_threads[crawler_type] = monitor


# ---- 优雅关闭 ----
def cleanup_running_crawler():
    """终止所有运行中的爬虫子进程"""
    state = _get_state_snapshot()
    processes = state['running_processes']
    if not processes:
        return

    for crawler_type, process in list(processes.items()):
        if process and process.poll() is None:
            logger.info("Cleaning up running crawler: %s (pid=%d)", crawler_type, process.pid)
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name != 'nt':
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait(timeout=5)
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Failed to clean up crawler %s: %s", crawler_type, e)


def shutdown_handler(signum=None, frame=None):
    """SIGTERM/SIGINT 处理"""
    logger.info("Received shutdown signal (signum=%s), cleaning up...", signum)
    cleanup_running_crawler()
    # 清理所有日志订阅
    with _subscriptions_lock:
        for sid, event in list(_log_subscriptions.items()):
            event.set()
        _log_subscriptions.clear()
    logger.info("Shutdown complete")
    sys.exit(0)


# 注册信号处理器
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)
atexit.register(cleanup_running_crawler)


def calculate_duration_seconds(timestamp_str):
    """根据开始时间计算已运行秒数"""
    if not timestamp_str:
        return 0
    try:
        start_time = to_local_time(datetime.fromisoformat(timestamp_str))
        return max(0, int((now_local() - start_time).total_seconds()))
    except Exception:
        logger.warning("Failed to parse timestamp: %s", timestamp_str)
        return 0



def build_crawler_command(crawler_type, config_path):
    """构建带配置文件路径的启动命令"""
    cmd_info = CRAWLER_COMMANDS[crawler_type]
    return [*cmd_info['cmd'], '--config', config_path]



def get_latest_record_for_crawler(crawler_name):
    """获取指定爬虫最近一条历史记录"""
    history = sorted(load_history(), key=lambda item: item.get('timestamp', ''), reverse=True)
    for record in history:
        if record.get('crawler_type') == crawler_name and record.get('config_file'):
            return record
    return None



def get_record_runtime_params(record):
    """从历史记录对应的配置文件读取 GUI 参数快照"""
    if not record:
        return None
    crawler_type = record.get('crawler_type')
    config_file = record.get('config_file')
    if not crawler_type or not config_file:
        return None
    config_payload = load_runtime_config(crawler_type, config_file)
    if not isinstance(config_payload, dict):
        return None
    gui_params = config_payload.get('_gui_params')
    if isinstance(gui_params, dict):
        return gui_params
    return config_payload


# ==================== 页面路由 ====================

@app.route('/')
def index():
    """主页面 - 直接返回静态 HTML，避免 Jinja2 解析"""
    return send_file('templates/index.html')


@app.route('/test')
def test():
    """测试页面 - 验证 Vue 是否正常工作"""
    return send_file('templates/test.html')


def _check_database_status():
    """检测数据库连接状态（仅探测可达性，不抛出异常）"""
    db_status = {'mysql': 'not_configured', 'mongo': 'not_configured', 'sqlite': 'not_configured'}
    try:
        # MySQL 检测
        from config import DEFAULT_SETTINGS
        mysql_cfg = DEFAULT_SETTINGS.get('mysql_config', {})
        mongo_cfg = DEFAULT_SETTINGS.get('mongo_config', {})
        sqlite_cfg = DEFAULT_SETTINGS.get('sqlite_config', {})

        # SQLite（仅检查目录是否存在）
        if sqlite_cfg.get('enabled'):
            sqlite_dir = os.environ.get('SQLITE_DATA_DIR', '/app/data/sqlite')
            if os.path.isdir(sqlite_dir) and os.access(sqlite_dir, os.W_OK):
                db_status['sqlite'] = 'available'
            else:
                db_status['sqlite'] = 'unavailable'

        # MySQL（仅检查容器网络可达性）
        if mysql_cfg.get('enabled'):
            try:
                import pymysql
                conn = pymysql.connect(
                    host=os.environ.get('MYSQL_HOST', 'weibo-mysql'),
                    port=int(os.environ.get('MYSQL_PORT', '3306')),
                    user=os.environ.get('MYSQL_USER', 'root'),
                    password=os.environ.get('MYSQL_PASSWORD', ''),
                    connect_timeout=3,
                )
                conn.close()
                db_status['mysql'] = 'available'
            except Exception:
                db_status['mysql'] = 'unavailable'

        # MongoDB（仅检查容器网络可达性）
        if mongo_cfg.get('enabled'):
            try:
                from pymongo import MongoClient
                uri = os.environ.get('MONGODB_URI', 'mongodb://weibo-mongo:27017/')
                client = MongoClient(uri, serverSelectionTimeoutMS=3000)
                client.admin.command('ping')
                client.close()
                db_status['mongo'] = 'available'
            except Exception:
                db_status['mongo'] = 'unavailable'
    except Exception:
        pass
    return db_status


@app.route('/health')
def health_check():
    """健康检查端点（用于 Docker healthcheck / 容器编排）"""
    state = _get_state_snapshot()
    status_code = 200
    status_msg = 'healthy'
    if any(p and p.poll() is None for p in state['running_processes'].values()):
        status_msg = 'crawler_running'
    db_status = _check_database_status()
    return jsonify({
        'status': status_msg,
        'timestamp': now_local().isoformat(),
        'databases': db_status,
    }), status_code


# ==================== API 路由 ====================

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取设置"""
    return jsonify(load_settings())


@app.route('/api/settings', methods=['POST'])
def save_settings_api():
    """保存设置"""
    data = request.json
    if save_settings(data):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '保存失败'}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """获取运行状态"""
    return jsonify(load_status())


@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史记录"""
    history = sorted(load_history(), key=lambda item: item.get('timestamp', ''), reverse=True)

    for record in history:
        record['time_display'] = format_time_display(record.get('timestamp', ''))
        record['crawler_name'] = record.get('crawler_type', '')
        record['start_time'] = record.get('timestamp', '')
        record['end_time'] = '' if record.get('status') == 'running' else record.get('finished_at') or record.get('timestamp', '')
        record['summary'] = record.get('summary', '')
        record['has_log'] = bool(record.get('log_filename'))
        record['has_config'] = bool(record.get('config_file'))

    return jsonify(history)


@app.route('/api/history', methods=['DELETE'])
@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    """清空历史记录并联动删除配置文件"""
    history = load_history()
    if any(item.get('status') == 'running' for item in history):
        return jsonify({'success': False, 'error': '存在运行中的任务，不能清空历史'}), 400

    for record in history:
        delete_runtime_config(record.get('crawler_type'), record.get('config_file'))

    if save_history([]):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '清空失败'}), 500


@app.route('/api/history/<record_id>', methods=['DELETE'])
def delete_history_record(record_id):
    """删除单条历史记录并联动删除配置文件"""
    history = load_history()
    target_record = next((item for item in history if item.get('id') == record_id), None)
    if not target_record:
        return jsonify({'success': False, 'error': '历史记录不存在'}), 404
    if target_record.get('status') == 'running':
        return jsonify({'success': False, 'error': '运行中的任务不能删除'}), 400

    delete_runtime_config(target_record.get('crawler_type'), target_record.get('config_file'))
    history = [h for h in history if h.get('id') != record_id]
    if save_history(history):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '删除失败'}), 500


@app.route('/api/last-params/<crawler_name>', methods=['GET'])
def get_last_params(crawler_name):
    """获取指定爬虫最近一次历史对应的配置参数"""
    record = get_latest_record_for_crawler(crawler_name)
    params = get_record_runtime_params(record)
    if params is None:
        return jsonify({}), 404
    return jsonify(params)


@app.route('/api/history/<record_id>/params', methods=['GET'])
def get_history_params(record_id):
    """读取指定历史记录关联的配置参数"""
    record = get_history_record(record_id)
    params = get_record_runtime_params(record)
    if params is None:
        return jsonify({'success': False, 'error': '未找到对应配置文件'}), 404
    return jsonify({'success': True, 'params': params})


@app.route('/api/history/keep_recent', methods=['POST'])
def keep_recent_history():
    """保留最近 N 条历史记录，并清理被移除记录的配置文件"""
    data = request.json or {}
    n = data.get('n', 100)

    history = load_history()
    kept_history = history[:n]
    removed_history = history[n:]

    if any(item.get('status') == 'running' for item in removed_history):
        return jsonify({'success': False, 'error': '待删除的历史中存在运行中的任务'}), 400

    for record in removed_history:
        delete_runtime_config(record.get('crawler_type'), record.get('config_file'))

    if save_history(kept_history):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '操作失败'}), 500


# ==================== 兼容前端请求的别名路由 ====================

@app.route('/api/crawler/start', methods=['POST'])
@require_auth
def start_crawler():
    """启动爬虫"""
    data = request.json or {}
    crawler_type = data.get('crawler_type')
    params = data.get('params', {})

    # 线程安全地检查同类型爬虫是否已在运行
    with state_lock:
        existing_process = running_processes.get(crawler_type)
        if existing_process and existing_process.poll() is None:
            return jsonify({'success': False, 'error': f'{crawler_type} 已在运行中'}), 400

    settings = load_settings()
    global_cookie = settings.get('cookie', '')
    mysql_config = settings.get('mysql_config', {})
    # 过滤掉前端 UI 字段，避免透传到数据库连接参数
    mysql_config.pop('enabled', None)
    mysql_config.pop('default_enabled', None)
    mongo_config = settings.get('mongo_config', {})
    mongo_config.pop('enabled', None)
    mongo_config.pop('default_enabled', None)
    sqlite_config = settings.get('sqlite_config', {})
    sqlite_config.pop('enabled', None)
    sqlite_config.pop('default_enabled', None)
    start_time = now_local()

    try:
        generated_config_path = None
        if crawler_type == 'weibo-crawler':
            generated_config_path = generate_weibo_crawler_config(params, global_cookie, mysql_config, mongo_config=mongo_config, sqlite_config=sqlite_config, timestamp=start_time)
        elif crawler_type == 'weibo-follow':
            generated_config_path = generate_weibo_follow_config(params, global_cookie, mysql_config, mongo_config=mongo_config, sqlite_config=sqlite_config, timestamp=start_time)
        elif crawler_type == 'weibo-search':
            generated_config_path = generate_weibo_search_config(params, global_cookie, mysql_config, mongo_config=mongo_config, sqlite_config=sqlite_config, timestamp=start_time)
        else:
            return jsonify({'success': False, 'error': '未知的爬虫类型'}), 400

        with open(generated_config_path, 'r', encoding='utf-8') as config_file:
            generated_config = json.load(config_file)
        config_file_name = os.path.basename(generated_config_path)
    except Exception as e:
        logger.error("生成配置失败: %s", e)
        return jsonify({'success': False, 'error': f'生成配置失败: {str(e)}'}), 500

    log_file = get_log_file_path(crawler_type, start_time)
    log_filename = os.path.basename(log_file)
    history_id = add_history_record(
        crawler_type,
        config_file_name,
        generated_config,
        'running',
        started_at=start_time,
        log_filename=log_filename,
    )

    try:
        cmd_info = CRAWLER_COMMANDS[crawler_type]
        cwd = CRAWLER_PATHS[cmd_info['cwd_key']]
        cmd = build_crawler_command(crawler_type, generated_config_path)

        # 传递 cookie 通过环境变量（不落入磁盘 JSON 文件）
        subprocess_env = os.environ.copy()
        if global_cookie:
            subprocess_env['WEIBO_COOKIE'] = global_cookie

        with open(log_file, 'w', encoding='utf-8') as f:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None,
                env=subprocess_env,
            )

        # 线程安全地更新全局状态
        _set_crawler_state(
            crawler_type=crawler_type,
            process=process,
            history_id=history_id,
        )

        # 加载现有状态并合并新的爬虫状态
        existing_status = load_status()
        running_crawlers = existing_status.get('running_crawlers', {})
        running_crawlers[crawler_type] = {
            'pid': process.pid,
            'history_id': history_id,
            'log_filename': log_filename,
        }
        save_status({'running_crawlers': running_crawlers})

        # 启动监控线程（含超时保护）
        monitor = threading.Thread(
            target=monitor_process,
            args=(process, crawler_type, history_id, start_time),
            daemon=True,
        )
        monitor.start()
        _set_crawler_state(crawler_type=crawler_type, monitor=monitor)

        return jsonify({
            'success': True,
            'history_id': history_id,
            'pid': process.pid,
            'log_filename': log_filename,
        })

    except Exception as e:
        logger.exception("启动爬虫失败")
        update_history_record(
            history_id,
            status='failed',
            summary=generate_output_summary(crawler_type, generated_config, 'failed'),
            exit_code=-1,
            failure_reason=str(e),
            log_filename=log_filename,
            stop_requested=False,
        )
        # 清除该类型的状态
        existing_status = load_status()
        running_crawlers = existing_status.get('running_crawlers', {})
        running_crawlers.pop(crawler_type, None)
        save_status({'running_crawlers': running_crawlers})
        _set_crawler_state(crawler_type=crawler_type, process=None, history_id=None, monitor=None)
        return jsonify({'success': False, 'error': f'启动失败: {str(e)}'}), 500


@app.route('/api/crawler/stop', methods=['POST'])
@require_auth
def stop_crawler():
    """停止爬虫（支持按类型指定，不指定则停止第一个运行中的）"""
    data = request.json or {}
    req_crawler_type = data.get('crawler_type')
    state = _get_state_snapshot()

    if req_crawler_type:
        # 按指定类型停止
        process = state['running_processes'].get(req_crawler_type)
        crawler_type = req_crawler_type
        history_id = state['running_history_ids'].get(req_crawler_type)
        if not process:
            return jsonify({'success': False, 'error': f'{req_crawler_type} 没有运行中的实例'}), 400
    else:
        # 向后兼容：不指定类型则停止第一个运行中的爬虫
        crawler_type = None
        process = None
        for ct, p in state['running_processes'].items():
            if p and p.poll() is None:
                crawler_type = ct
                process = p
                history_id = state['running_history_ids'].get(ct)
                break
        if not process:
            return jsonify({'success': False, 'error': '没有运行中的爬虫'}), 400

    try:
        pid = process.pid

        if history_id:
            update_history_record(
                history_id,
                summary='用户请求停止，等待进程退出...',
                stop_requested=True,
            )

        # 优雅终止（SIGTERM）
        if pid:
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    logger.info("Sent SIGTERM to pid=%d, crawler_type=%s", pid, crawler_type)
                else:
                    process.terminate()
            except (ProcessLookupError, OSError) as e:
                logger.warning("SIGTERM failed for pid=%d: %s", pid, e)

        # 等待进程退出
        try:
            process.wait(timeout=10)
            logger.info("Process pid=%d exited gracefully", pid)
        except subprocess.TimeoutExpired:
            # 超时则强制 SIGKILL
            logger.warning("Process pid=%d timeout, sending SIGKILL", pid)
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)
                logger.info("Process pid=%d killed", pid)
            except (ProcessLookupError, OSError) as e:
                logger.warning("SIGKILL failed for pid=%d: %s", pid, e)
            except subprocess.TimeoutExpired:
                logger.error("Process pid=%d did not respond to SIGKILL", pid)

        # 线程安全地清除该类型爬虫状态
        _set_crawler_state(crawler_type=crawler_type, process=None, history_id=None, monitor=None)
        existing_status = load_status()
        running_crawlers = existing_status.get('running_crawlers', {})
        running_crawlers.pop(crawler_type, None)
        save_status({'running_crawlers': running_crawlers})

        return jsonify({'success': True})

    except Exception as e:
        logger.exception("停止爬虫失败")
        if history_id:
            record = get_history_record(history_id) or {}
            update_history_record(
                history_id,
                summary='停止失败，请查看日志',
                duration=calculate_duration_seconds(record.get('timestamp')),
                stop_requested=False,
            )
        # 仅当成功获取了 crawler_type 才做清理
        if 'crawler_type' in dir() and crawler_type:
            _set_crawler_state(crawler_type=crawler_type, process=None, history_id=None, monitor=None)
            existing_status = load_status()
            running_crawlers = existing_status.get('running_crawlers', {})
            running_crawlers.pop(crawler_type, None)
            save_status({'running_crawlers': running_crawlers})
        return jsonify({'success': False, 'error': f'停止失败: {str(e)}'}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """获取日志列表"""
    return jsonify(list_all_logs())


@app.route('/api/logs', methods=['DELETE'])
def clear_all_logs_api():
    """清空全部日志文件"""
    deleted_count = clear_all_log_files()
    return jsonify({'success': True, 'deleted_count': deleted_count})


@app.route('/api/logs/file/<path:filename>', methods=['GET'])
def get_log_content_by_filename(filename):
    """按文件名获取日志内容"""
    lines = request.args.get('lines', 100, type=int)
    content = read_log_file(filename, lines)
    if content is None:
        return jsonify({'content': '日志文件不存在'}), 404
    return jsonify({'content': content})


@app.route('/api/logs/<crawler_type>', methods=['GET'])
def get_log_content(crawler_type):
    """获取指定爬虫最新日志内容（兼容旧版接口）"""
    lines = request.args.get('lines', 100, type=int)
    content = read_log_tail(crawler_type, lines)
    return jsonify({'content': ''.join(content)})


@app.route('/api/logs/<crawler_type>/clear', methods=['POST', 'DELETE'])
def clear_log(crawler_type):
    """清空指定爬虫日志"""
    if clear_log_file(crawler_type):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '未找到可清空的日志'}), 404


@app.route('/api/logs/delete', methods=['POST'])
def delete_log():
    """删除日志文件"""
    data = request.json or {}
    filename = data.get('filename')
    if delete_log_file(filename):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '删除失败'}), 404


@app.route('/api/logs/<path:filename>', methods=['DELETE'])
def delete_log_by_filename(filename):
    """按文件名删除日志 (兼容前端)"""
    if delete_log_file(filename):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '删除失败'}), 404


@app.route('/api/cookie/verify', methods=['POST'])
def verify_cookie():
    """验证 Cookie 有效性 —— 实际请求微博 API 检查登录状态"""
    data = request.json
    cookie = data.get('cookie', '')

    if not cookie or 'SUB=' not in cookie:
        return jsonify({'valid': False, 'message': 'Cookie 格式不正确，需要包含 SUB 字段'})

    # 提取 SUB 值
    match = re.search(r'SUB=(.*?)(;|$)', cookie)
    if not match or not match.group(1):
        return jsonify({'valid': False, 'message': 'Cookie 中 SUB 值为空'})

    sub_value = match.group(1)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://m.weibo.cn/',
        'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8',
    }

    try:
        # 请求微博首页，跟随重定向以检测是否被踢到登录页
        resp = requests.get(
            'https://m.weibo.cn',
            headers=headers,
            cookies={'SUB': sub_value},
            timeout=10,
            allow_redirects=True,
        )

        final_url = resp.url.lower()
        text_lower = resp.text[:8000].lower()

        # 检查1：被重定向到登录/通行证页面 → 明确失效
        if 'passport.weibo.com' in final_url or 'login.sina.com.cn' in final_url:
            return jsonify({'valid': False, 'message': 'Cookie 已失效，被重定向到登录页'})

        # 检查2：响应内容中包含登录入口关键词 → 明确失效
        login_indicators = ['passport.weibo.com', 'login.sina.com.cn', '/login.php']
        if any(ind in text_lower for ind in login_indicators):
            return jsonify({'valid': False, 'message': 'Cookie 已失效，页面要求登录'})

        # 检查3：响应头中服务器清除了 SUB → 明确失效
        set_cookie = resp.headers.get('Set-Cookie', '')
        if 'SUB=;' in set_cookie or 'SUB=deleted' in set_cookie:
            return jsonify({'valid': False, 'message': 'Cookie 已被服务器拒绝'})

        # 以上失效特征均未命中，判定 Cookie 有效
        return jsonify({'valid': True, 'message': 'Cookie 有效'})

    except requests.exceptions.Timeout:
        return jsonify({'valid': False, 'message': '连接微博超时，请检查网络'})
    except Exception as e:
        return jsonify({'valid': False, 'message': f'验证请求失败: {str(e)}'})


@app.route('/api/mysql/test', methods=['POST'])
def test_mysql():
    """测试 MySQL 连接"""
    data = request.json
    mysql_config = data.get('mysql_config', {})
    
    try:
        import pymysql
        conn = pymysql.connect(
            host=mysql_config.get('host', 'localhost'),
            port=mysql_config.get('port', 3306),
            user=mysql_config.get('user', 'root'),
            password=mysql_config.get('password', ''),
            database=mysql_config.get('database', ''),
            charset=mysql_config.get('charset', 'utf8mb4'),
            connect_timeout=5
        )
        conn.close()
        return jsonify({'success': True, 'message': '连接成功'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/mongo/test', methods=['POST'])
def test_mongo():
    """测试 MongoDB 连接"""
    data = request.json or {}
    mongo_uri = data.get('mongo_uri', 'mongodb://weibo-mongo:27017/')
    try:
        from pymongo import MongoClient
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        client.close()
        return jsonify({'success': True, 'message': '连接成功'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/sqlite/test', methods=['POST'])
def test_sqlite():
    """测试 SQLite 数据库路径可用性"""
    data = request.json or {}
    db_path = data.get('db_path', '/app/data/sqlite/weibodata.db')
    try:
        import sqlite3
        import os
        # 确保目录存在
        dir_path = os.path.dirname(db_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        # 尝试连接并创建表（验证可写性）
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS _connection_test (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO _connection_test (id) VALUES (1)")
        cursor.execute("DELETE FROM _connection_test")
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '路径可用'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== 进程监控 ====================

def monitor_process(process, crawler_type, history_id, start_time=None):
    """监控进程状态（含超时保护）"""
    start_time = start_time or now_local()

    try:
        process.wait()
    except Exception as e:
        logger.error("monitor_process wait() exception: %s", e)

    elapsed = (now_local() - start_time).total_seconds()
    logger.info("Crawler %s finished: pid=%d, exit_code=%d, elapsed=%.0fs",
                crawler_type, process.pid, process.returncode, elapsed)

    record = get_history_record(history_id) or {}
    config_payload = load_runtime_config(crawler_type, record.get('config_file')) or {}
    duration = int(calculate_duration_seconds(record.get('timestamp')))
    log_filename = record.get('log_filename')
    exit_code = process.returncode
    stop_requested = bool(record.get('stop_requested'))

    if stop_requested:
        status = 'stopped'
        failure_reason = ''
    elif exit_code == 0:
        status = 'success'
        failure_reason = ''
    else:
        status = 'failed'
        failure_reason = summarize_failure_from_log(log_filename, exit_code)

    summary = generate_output_summary(crawler_type, config_payload, status)

    update_history_record(
        history_id,
        status=status,
        duration=duration,
        summary=summary,
        exit_code=exit_code,
        failure_reason=failure_reason,
        log_filename=log_filename,
        stop_requested=False,
    )

    # 线程安全地清除该类型爬虫状态
    _set_crawler_state(crawler_type=crawler_type, process=None, history_id=None, monitor=None)
    existing_status = load_status()
    running_crawlers = existing_status.get('running_crawlers', {})
    running_crawlers.pop(crawler_type, None)
    save_status({'running_crawlers': running_crawlers})

    socketio.emit('crawler_finished', {
        'crawler_type': crawler_type,
        'status': status,
        'history_id': history_id,
        'log_filename': log_filename,
        'exit_code': exit_code,
        'failure_reason': failure_reason,
    })


# ==================== WebSocket ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    emit('connected', {'data': 'Connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开时清理该连接的日志订阅"""
    sid = request.sid
    with _subscriptions_lock:
        event = _log_subscriptions.pop(sid, None)
    if event:
        logger.info("Client %s disconnected, cleaning up log subscription", sid)
        event.set()


@socketio.on('unsubscribe_log')
def handle_unsubscribe_log(data=None):
    """取消日志订阅"""
    sid = request.sid
    crawler_type = (data or {}).get('crawler_type', 'unknown') if data else 'unknown'
    with _subscriptions_lock:
        event = _log_subscriptions.pop(sid, None)
    if event:
        logger.info("Client %s unsubscribed from %s logs", sid, crawler_type)
        event.set()
        socketio.emit('log_unsubscribed', {'crawler_type': crawler_type}, room=sid)


@socketio.on('subscribe_log')
def handle_subscribe_log(data):
    """订阅日志（有退出条件，不再泄漏）"""
    sid = request.sid
    crawler_type = data.get('crawler_type')

    # 取消该客户端之前的订阅（避免重复订阅累积）
    with _subscriptions_lock:
        old_event = _log_subscriptions.pop(sid, None)
    if old_event:
        logger.info("Client %s re-subscribing, cleaning old subscription", sid)
        old_event.set()

    stop_event = threading.Event()
    with _subscriptions_lock:
        _log_subscriptions[sid] = stop_event

    def send_log():
        logger.info("Client %s subscribed to %s logs", sid, crawler_type)
        try:
            while not stop_event.is_set():
                try:
                    content = read_log_tail(crawler_type, 100)
                    # 检查爬虫是否已停止（自动退出的附加条件）
                    state = _get_state_snapshot()
                    target_process = state['running_processes'].get(crawler_type)
                    crawler_done = (target_process is None or
                                    target_process.poll() is not None)

                    socketio.emit('log_update', {
                        'crawler_type': crawler_type,
                        'content': '\n'.join(content),
                        'crawler_done': crawler_done,
                    })

                    # 如果爬虫已结束，停止推送
                    if crawler_done:
                        logger.info("Crawler %s finished, stopping log push for %s", crawler_type, sid)
                        break

                    # 使用 stop_event 等待，超时则继续（接收 stop 信号）
                    stop_event.wait(1)
                except Exception as e:
                    logger.warning("Log push error for %s: %s", sid, e)
                    if not stop_event.is_set():
                        stop_event.wait(2)
        finally:
            # 确保清理
            with _subscriptions_lock:
                _log_subscriptions.pop(sid, None)
            logger.info("Client %s log subscription cleaned up", sid)

    socketio.start_background_task(send_log)


# ==================== 主程序 ====================

if __name__ == '__main__':
    port = FLASK_PORT
    logger.info("Starting server on http://%s:%d", FLASK_HOST, port)
    if API_TOKEN:
        logger.info("API Token authentication: ENABLED")
    else:
        logger.warning("API Token authentication: DISABLED (set API_TOKEN env var to enable)")
    socketio.run(app, host=FLASK_HOST, port=port, debug=FLASK_DEBUG, allow_unsafe_werkzeug=True)
