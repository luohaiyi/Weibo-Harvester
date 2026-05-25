"""
工具函数模块
"""
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


_UNSET = object()

logger = logging.getLogger(__name__)


def _atomic_write_json(filepath, data):
    """原子写入 JSON 文件：先写临时文件，再 os.replace 原子替换。
    
    避免写入过程中崩溃导致文件损坏或数据丢失。
    os.replace 在 Unix 上是原子操作（同文件系统内）。
    """
    temp_path = filepath + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, filepath)
        return True
    except Exception as e:
        logger.error(f"原子写入 JSON 失败 [{filepath}]: {e}")
        # 清理临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def _load_config_constants():
    """延迟加载 config 常量，避免循环导入"""
    from config import (
        SETTINGS_FILE,
        STATUS_FILE,
        DEFAULT_SETTINGS,
        LOGS_DIR,
        HISTORY_FILE,
        CRAWLER_NAME_MAP,
        RUNTIME_CONFIG_PATHS,
    )

    return SETTINGS_FILE, STATUS_FILE, DEFAULT_SETTINGS, LOGS_DIR, HISTORY_FILE, CRAWLER_NAME_MAP, RUNTIME_CONFIG_PATHS


SETTINGS_FILE, STATUS_FILE, DEFAULT_SETTINGS, LOGS_DIR, HISTORY_FILE, CRAWLER_NAME_MAP, RUNTIME_CONFIG_PATHS = _load_config_constants()


def _ensure_gui_runtime_dirs():
    """确保 GUI 运行时目录存在"""
    from config import ensure_temp_dir

    ensure_temp_dir()


STATUS_DEFAULTS = {
    'running_crawlers': {},  # {crawler_type: {pid, history_id, log_filename}}
}

HISTORY_RECORD_DEFAULTS = {
    'id': '',
    'crawler_type': '',
    'timestamp': '',
    'finished_at': None,
    'status': 'running',
    'duration': 0,
    'config_file': '',
    'summary': '',
    'log_filename': '',
    'exit_code': None,
    'failure_reason': '',
    'stop_requested': False,
    'output_targets': [],
}


def get_timezone():
    """获取用户配置的时区，默认 Asia/Shanghai"""
    settings = load_settings()
    tz_name = settings.get('timezone', 'Asia/Shanghai')
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo('Asia/Shanghai')



def to_local_time(dt):
    """将时间转换为用户配置的本地时区"""
    if dt is None:
        return None
    local_tz = get_timezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(local_tz)



def now_local():
    """获取当前本地时间（带时区）"""
    return datetime.now(get_timezone())



def ensure_runtime_config_dir(crawler_type):
    """确保指定爬虫的运行配置目录存在"""
    _ensure_gui_runtime_dirs()
    config_dir = RUNTIME_CONFIG_PATHS.get(crawler_type)
    if not config_dir:
        raise ValueError(f'未知的爬虫类型: {crawler_type}')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir



def generate_runtime_config_filename(crawler_type, timestamp=None, unique_id=None):
    """生成唯一配置文件名"""
    timestamp = timestamp or now_local()
    unique_id = unique_id or str(uuid.uuid4())
    return f"{crawler_type}_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"



def get_runtime_config_path(crawler_type, config_file):
    """根据爬虫类型和文件名解析配置文件绝对路径"""
    if not crawler_type or not config_file:
        return ''
    config_dir = RUNTIME_CONFIG_PATHS.get(crawler_type)
    if not config_dir:
        return ''
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, os.path.basename(config_file))



def save_runtime_config(crawler_type, config_payload, timestamp=None):
    """保存运行配置文件，返回 (文件名, 绝对路径)（原子写入）"""
    config_dir = ensure_runtime_config_dir(crawler_type)
    config_file = generate_runtime_config_filename(crawler_type, timestamp=timestamp)
    config_path = os.path.join(config_dir, config_file)
    _atomic_write_json(config_path, config_payload)
    return config_file, config_path



def load_runtime_config(crawler_type, config_file):
    """读取运行配置文件"""
    config_path = get_runtime_config_path(crawler_type, config_file)
    if not config_path or not os.path.exists(config_path):
        return None
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)



def delete_runtime_config(crawler_type, config_file):
    """删除运行配置文件，不存在时视为成功"""
    config_path = get_runtime_config_path(crawler_type, config_file)
    if not config_path or not os.path.exists(config_path):
        return True
    os.remove(config_path)
    return True



def extract_gui_params(config_or_params):
    """从运行配置中提取 GUI 参数快照；若本身就是参数对象则原样返回"""
    if isinstance(config_or_params, dict):
        gui_params = config_or_params.get('_gui_params')
        if isinstance(gui_params, dict):
            return gui_params
        return config_or_params
    return {}



def format_time_display(timestamp_str):
    """格式化时间显示（按本地时区展示）"""
    try:
        dt = to_local_time(datetime.fromisoformat(timestamp_str))
        now = now_local()
        today = now.date()
        record_date = dt.date()

        if record_date == today:
            return f"今天 {dt.strftime('%H:%M:%S')}"
        if (today - record_date).days == 1:
            return f"昨天 {dt.strftime('%H:%M:%S')}"
        if record_date.year == today.year:
            return dt.strftime('%m-%d %H:%M:%S')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return timestamp_str



def merge_settings(user_settings, default_settings):
    """递归合并设置"""
    result = default_settings.copy()
    for key, value in user_settings.items():
        if key in result and isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = merge_settings(value, result[key])
        else:
            result[key] = value
    return result



def load_settings():
    """加载设置文件"""
    _ensure_gui_runtime_dirs()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                return merge_settings(settings, DEFAULT_SETTINGS)
        except Exception as e:
            logger.error("加载设置文件失败: %s", e)
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()



def save_settings(settings):
    """保存设置文件（原子写入）"""
    _ensure_gui_runtime_dirs()
    return _atomic_write_json(SETTINGS_FILE, settings)



def load_status():
    """加载状态文件"""
    _ensure_gui_runtime_dirs()
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                raw_status = json.load(f)
                if isinstance(raw_status, dict):
                    return {**STATUS_DEFAULTS, **raw_status}
        except Exception as e:
            logger.error("加载状态文件失败: %s", e)
    return STATUS_DEFAULTS.copy()



def save_status(status):
    """保存状态文件（原子写入）"""
    _ensure_gui_runtime_dirs()
    payload = {**STATUS_DEFAULTS, **(status or {})}
    return _atomic_write_json(STATUS_FILE, payload)



def normalize_history_record(record):
    """补齐历史记录的默认字段，兼容旧数据结构，并清理废弃字段"""
    if not isinstance(record, dict):
        record = {}

    normalized = {
        key: record.get(key, default)
        for key, default in HISTORY_RECORD_DEFAULTS.items()
    }

    legacy_summary = record.get('summary') or record.get('output_summary') or ''
    normalized['summary'] = legacy_summary
    normalized['config_file'] = os.path.basename((normalized.get('config_file') or '').strip())

    output_targets = normalized.get('output_targets')
    if isinstance(output_targets, list):
        normalized['output_targets'] = [str(item) for item in output_targets if item]
    elif output_targets:
        normalized['output_targets'] = [str(output_targets)]
    else:
        normalized['output_targets'] = []

    if normalized.get('exit_code') in ('', 'None'):
        normalized['exit_code'] = None

    duration = normalized.get('duration')
    try:
        normalized['duration'] = int(duration or 0)
    except Exception:
        normalized['duration'] = 0

    normalized['failure_reason'] = (normalized.get('failure_reason') or '').strip()
    normalized['log_filename'] = (normalized.get('log_filename') or '').strip()
    normalized['stop_requested'] = bool(normalized.get('stop_requested'))

    return normalized



def load_history():
    """加载历史记录文件"""
    _ensure_gui_runtime_dirs()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if isinstance(history, list):
                    return [normalize_history_record(item) for item in history]
        except Exception as e:
            logger.error("加载历史记录失败: %s", e)
            return []
    return []



def save_history(history):
    """保存历史记录文件（原子写入）"""
    _ensure_gui_runtime_dirs()
    normalized_history = [normalize_history_record(item) for item in history if isinstance(item, dict)]
    return _atomic_write_json(HISTORY_FILE, normalized_history)



def migrate_history_from_settings():
    """从 settings.json 迁移历史记录到独立文件"""
    settings = load_settings()
    history = settings.get('history', [])
    if history:
        save_history(history)
        settings['history'] = []
        save_settings(settings)
        logger.info("已迁移 %d 条历史记录到独立文件", len(history))
    return history


_ensure_gui_runtime_dirs()
if not os.path.exists(HISTORY_FILE):
    migrate_history_from_settings()



def generate_history_id():
    """生成历史记录ID"""
    return str(uuid.uuid4())



def get_history_record(history_id):
    """按 ID 获取单条历史记录"""
    for record in load_history():
        if record.get('id') == history_id:
            return record
    return None



def extract_output_targets(crawler_type, config_or_params):
    """从运行配置或 GUI 参数快照中提取主要输出目标"""
    params = extract_gui_params(config_or_params)
    targets = []

    if crawler_type == 'weibo-crawler':
        output_directory = str(params.get('output_directory') or '').strip()
        if output_directory in ('', '.', './', 'weibo', 'weibo_data'):
            output_directory = '/app/data/weibo-crawler'
        if output_directory:
            targets.append(output_directory)

        write_mode = params.get('write_mode', [])
        if isinstance(write_mode, str):
            write_mode = [write_mode]
        if 'sqlite' in write_mode:
            sqlite_data_dir = os.environ.get("SQLITE_DATA_DIR", "/app/data/sqlite")
            sqlite_db_path = str(params.get('sqlite_db_path') or '').strip()
            if sqlite_db_path in ('', '.', './', 'weibodata.db'):
                sqlite_db_path = os.path.join(sqlite_data_dir, 'weibodata.db')
            elif sqlite_db_path and not os.path.isabs(sqlite_db_path):
                sqlite_db_path = os.path.join(output_directory or sqlite_data_dir, sqlite_db_path)
            if sqlite_db_path and sqlite_db_path not in targets:
                targets.append(sqlite_db_path)

    elif crawler_type == 'weibo-follow':
        output_filename = str(params.get('output_filename') or '').strip()
        if output_filename:
            targets.append(output_filename)
        if params.get('use_sqlite'):
            sqlite_db_path = str(params.get('sqlite_db_path') or '').strip()
            if not sqlite_db_path:
                sqlite_db_path = os.path.join(
                    os.environ.get('SQLITE_DATA_DIR', '/app/data/sqlite'), 'weibo_follow.db')
            if sqlite_db_path and sqlite_db_path not in targets:
                targets.append(sqlite_db_path)

    elif crawler_type == 'weibo-search':
        files_store = str(params.get('files_store') or params.get('FILES_STORE') or '').strip()
        if files_store in ('', '.', './', '结果文件'):
            files_store = '/app/data/weibo-search/files'
        elif files_store and not os.path.isabs(files_store):
            files_store = os.path.join('/app/data/weibo-search', files_store)
        if files_store:
            targets.append(files_store)

        if params.get('use_images') or params.get('use_videos'):
            images_store = str(params.get('images_store') or params.get('IMAGES_STORE') or '').strip()
            if images_store in ('', '.', './', '结果文件'):
                images_store = '/app/data/weibo-search/images'
            elif images_store and not os.path.isabs(images_store):
                images_store = os.path.join('/app/data/weibo-search', images_store)
            if images_store and images_store not in targets:
                targets.append(images_store)

    return targets



def add_history_record(crawler_type, config_file, config_or_params, status='running', started_at=None, log_filename=None, output_targets=None):
    """添加历史记录"""
    history = load_history()
    started_at = started_at or now_local()
    record = normalize_history_record({
        'id': generate_history_id(),
        'crawler_type': crawler_type,
        'timestamp': started_at.isoformat() if hasattr(started_at, 'isoformat') else str(started_at),
        'finished_at': None,
        'status': status,
        'duration': 0,
        'config_file': config_file,
        'summary': generate_output_summary(crawler_type, config_or_params or {}, status),
        'log_filename': log_filename or '',
        'exit_code': None,
        'failure_reason': '',
        'stop_requested': False,
        'output_targets': output_targets if output_targets is not None else extract_output_targets(crawler_type, config_or_params),
    })

    if status != 'running' and not record.get('finished_at'):
        record['finished_at'] = now_local().isoformat()

    history.insert(0, record)
    save_history(history)
    return record['id']



def update_history_record(history_id, status=_UNSET, duration=_UNSET, summary=_UNSET, finished_at=_UNSET, **extra_updates):
    """更新历史记录"""
    history = load_history()
    protected_fields = {'id', 'crawler_type', 'timestamp', 'config_file'}

    for index, record in enumerate(history):
        if record.get('id') != history_id:
            continue

        updated_record = normalize_history_record(record)

        if status is not _UNSET:
            updated_record['status'] = status
            if finished_at is _UNSET:
                updated_record['finished_at'] = None if status == 'running' else now_local().isoformat()

        if duration is not _UNSET:
            updated_record['duration'] = duration

        if summary is not _UNSET:
            updated_record['summary'] = summary or ''

        if finished_at is not _UNSET:
            updated_record['finished_at'] = finished_at

        for key, value in extra_updates.items():
            if key in protected_fields or key not in HISTORY_RECORD_DEFAULTS:
                continue
            updated_record[key] = value

        history[index] = normalize_history_record(updated_record)
        save_history(history)
        return True

    return False



def generate_output_summary(crawler_type, config_or_params, status):
    """生成输出摘要"""
    params = extract_gui_params(config_or_params)

    # 状态前缀
    status_prefix = ''
    if status == 'running':
        status_prefix = '正在运行：'
    elif status == 'stopped':
        status_prefix = '用户手动停止：'
    elif status == 'failed':
        status_prefix = '运行失败：'
    elif status != 'success':
        return ''

    # 生成详细摘要（各状态通用）
    detail = ''
    if crawler_type == 'weibo-crawler':
        user_ids = params.get('user_id_list', [])
        if not user_ids:
            user_id_str = '未知'
        elif len(user_ids) == 1:
            user_id_str = str(user_ids[0])
        elif len(user_ids) == 2:
            user_id_str = f'{user_ids[0]}、{user_ids[1]}'
        else:
            user_id_str = f'{user_ids[0]}、{user_ids[1]} 等共{len(user_ids)}个ID'
        since = params.get('since_date', '')
        if isinstance(since, int) or (isinstance(since, str) and since.isdigit()):
            days = int(since) if isinstance(since, str) else since
            since_str = f'最近{days}天'
        else:
            since_str = since if since else '开始'
        end = params.get('end_date', '')
        end_str = end if end else datetime.now().strftime('%Y-%m-%d')
        detail = f'爬取用户 {user_id_str}，{since_str} 至 {end_str}'
    elif crawler_type == 'weibo-follow':
        user_ids = params.get('user_id_list', [])
        if not user_ids:
            user_id_str = '未知'
        elif len(user_ids) == 1:
            user_id_str = str(user_ids[0])
        elif len(user_ids) == 2:
            user_id_str = f'{user_ids[0]}、{user_ids[1]}'
        else:
            user_id_str = f'{user_ids[0]}、{user_ids[1]} 等共{len(user_ids)}个ID'
        detail = f'获取用户 {user_id_str} 的关注列表'
    elif crawler_type == 'weibo-search':
        keywords = params.get('keyword', '')
        today_str = datetime.now().strftime('%Y-%m-%d')
        start = params.get('start_time', '')
        end = params.get('end_time', '')
        start_str = start if start else today_str
        end_str = end if end else today_str
        detail = f'搜索关键词「{keywords}」，{start_str} 至 {end_str}'

    return f'{status_prefix}{detail}'



def ensure_logs_dir(log_key=None):
    """确保日志目录存在"""
    from config import ensure_logs_dir as config_ensure_logs_dir

    return config_ensure_logs_dir(log_key)



def get_log_file_path(crawler_type, timestamp=None):
    """获取日志文件路径"""
    from config import get_log_file_path as config_get_log_file_path

    return config_get_log_file_path(crawler_type, timestamp)



def _get_log_prefix(crawler_type):
    prefix = CRAWLER_NAME_MAP.get(crawler_type, '')
    return f'{prefix}_' if prefix else ''



def _iter_log_files():
    ensure_logs_dir()
    for current_root, _, files in os.walk(LOGS_DIR):
        for filename in files:
            if not filename.endswith('.log'):
                continue
            yield os.path.join(current_root, filename)



def _resolve_log_path(filename):
    if not filename:
        return None

    ensure_logs_dir()
    logs_root = os.path.realpath(LOGS_DIR)
    normalized = str(filename).strip().replace('\\', '/')

    if '/' in normalized:
        candidate = os.path.realpath(os.path.join(LOGS_DIR, normalized))
        if candidate == logs_root or not candidate.startswith(logs_root + os.sep):
            return None
        return candidate if os.path.isfile(candidate) else None

    matches = []
    for filepath in _iter_log_files():
        if os.path.basename(filepath) != normalized:
            continue
        try:
            matches.append((os.path.getmtime(filepath), filepath))
        except OSError:
            continue

    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]



def _format_file_size(size_bytes):
    value = float(size_bytes)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(value)} {unit}'
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{size_bytes} B'



def _shrink_text(text, max_length=180):
    compact = ' '.join((text or '').split())
    if len(compact) <= max_length:
        return compact
    return compact[:max_length - 1] + '…'



def find_latest_log_file(crawler_type):
    """查找指定爬虫最新的日志文件"""
    prefix = _get_log_prefix(crawler_type)
    if not prefix:
        return None

    candidates = []
    for filepath in _iter_log_files():
        filename = os.path.basename(filepath)
        if not (filename.startswith(prefix) and filename.endswith('.log')):
            continue
        try:
            candidates.append((os.path.getmtime(filepath), filepath))
        except OSError:
            continue

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]



def _read_file_tail(filepath, lines=100, chunk_size_guess=4096):
    """高效读取文件尾部 N 行，避免全量读取大文件导致 OOM。
    
    采用从尾部按块反向读取的策略：
    1. seek 到文件末尾
    2. 按块向前读取
    3. 直到收集到足够的换行符
    """
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []
    except OSError:
        return []

    try:
        with open(filepath, 'rb') as f:
            # 估算平均行长（保守：200 字节/行）
            estimated_size = lines * 200 + chunk_size_guess
            if file_size <= estimated_size:
                # 文件不大，直接全量读取
                f.seek(0)
                return f.read().decode('utf-8', errors='ignore').splitlines()

            # 从尾部反向读取
            f.seek(0, os.SEEK_END)
            buffer = bytearray()
            chunks_read = 0
            max_chunks = 50  # 防止无限循环

            while chunks_read < max_chunks:
                chunk_start = max(0, f.tell() - chunk_size_guess)
                if chunk_start == 0:
                    # 到达文件开头
                    f.seek(0)
                    remaining = f.read(f.tell() + chunk_size_guess) if f.tell() > 0 else f.read()
                    buffer = bytearray(remaining) + buffer
                    break

                f.seek(chunk_start)
                chunk = f.read(chunk_size_guess)
                buffer = bytearray(chunk) + buffer
                f.seek(chunk_start)

                # 统计换行符数量
                newline_count = buffer.count(b'\n')
                if newline_count > lines:
                    break

                chunks_read += 1

            content = buffer.decode('utf-8', errors='ignore')
            all_lines = content.splitlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        logger.warning("读取文件尾部失败 [%s]: %s", filepath, e)
        return []


def read_log_tail(crawler_type, lines=100):
    """读取指定爬虫最新日志文件的尾部内容（高效尾部读取）"""
    log_file = find_latest_log_file(crawler_type)
    if not log_file:
        return []
    return _read_file_tail(log_file, lines)



def read_log_file(filename, lines=100):
    """按文件名读取日志内容（高效尾部读取）"""
    filepath = _resolve_log_path(filename)
    if not filepath:
        return None
    tail_lines = _read_file_tail(filepath, lines)
    if tail_lines:
        return '\n'.join(tail_lines)
    return ''



def summarize_failure_from_log(filename, exit_code=None, lines=80):
    """从日志尾部提炼失败原因，优先选取最像错误信息的最后一行"""
    content = read_log_file(filename, lines)
    if not content:
        return f'进程异常退出（exit code {exit_code}）' if exit_code not in (None, 0) else ''

    candidates = [line.strip() for line in content.splitlines() if line.strip()]
    keywords = (
        'traceback', 'error', 'exception', 'failed', 'fatal', 'denied',
        'not found', 'timeout', 'timed out', 'refused', 'abort', 'invalid',
    )

    for line in reversed(candidates):
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in keywords):
            return _shrink_text(line)

    for line in reversed(candidates):
        if line and not set(line).issubset({'-', '=', '*', '#'}) :
            return _shrink_text(line)

    return f'进程异常退出（exit code {exit_code}）' if exit_code not in (None, 0) else ''



def clear_log_file(crawler_type):
    """清空指定爬虫类型的所有日志文件"""
    prefix = _get_log_prefix(crawler_type)
    if not prefix:
        return False

    deleted = False
    for filepath in _iter_log_files():
        filename = os.path.basename(filepath)
        if not (filename.startswith(prefix) and filename.endswith('.log')):
            continue
        try:
            os.remove(filepath)
            deleted = True
        except Exception as e:
            logger.warning("清空日志失败 [%s]: %s", filepath, e)
    return deleted



def clear_all_logs():
    """清空全部日志文件"""
    deleted_count = 0
    for filepath in _iter_log_files():
        try:
            os.remove(filepath)
            deleted_count += 1
        except Exception as e:
            logger.warning("删除日志失败 [%s]: %s", filepath, e)
    return deleted_count



def list_all_logs():
    """列出所有日志文件"""
    logs = []
    for filepath in _iter_log_files():
        filename = os.path.basename(filepath)
        try:
            stat = os.stat(filepath)
            relative_path = os.path.relpath(filepath, LOGS_DIR).replace(os.sep, '/')
            category = relative_path.split('/', 1)[0] if '/' in relative_path else 'root'
            logs.append(
                {
                    'name': relative_path,
                    'filename': filename,
                    'category': category,
                    'size': _format_file_size(stat.st_size),
                    'size_bytes': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime, tz=get_timezone()).isoformat(),
                    'mtime': stat.st_mtime,
                }
            )
        except OSError:
            continue

    return sorted(logs, key=lambda item: item['mtime'], reverse=True)



def delete_log_file(filename):
    """删除日志文件"""
    filepath = _resolve_log_path(filename)
    if not filepath:
        return False
    try:
        os.remove(filepath)
        return True
    except Exception as e:
        logger.warning("删除日志失败 [%s]: %s", filepath, e)
        return False
