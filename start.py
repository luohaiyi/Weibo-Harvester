#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harvester CLI 管理工具
提供与 GUI 功能等价的终端交互入口。
"""

import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 在容器环境下可导入 GUI 工具模块
APP_ROOT = Path('/app')
GUI_DIR = APP_ROOT / 'gui-web'
if GUI_DIR.exists():
    sys.path.insert(0, str(GUI_DIR))

GUI_URL = f"http://localhost:{os.environ.get('FLASK_PORT', '5100')}"
LOGS_DIR = APP_ROOT / 'logs'
DATA_DIR = APP_ROOT / 'data'
HISTORY_FILE = GUI_DIR / 'config' / 'history.json'
SETTINGS_FILE = GUI_DIR / 'config' / 'settings.json'

TZ = os.environ.get('TZ', 'Asia/Shanghai')

# 运行中的爬虫 PID
running_pids = {}


def safe_strftime(fmt='%Y-%m-%d'):
    return datetime.now().strftime(fmt)


def input_required(prompt, default=''):
    """必填项输入，空则重试"""
    while True:
        val = input(prompt).strip()
        if val:
            return val
        if default:
            return default
        print('  此项为必填，请重新输入。')


def input_optional(prompt, default=''):
    """可选项输入"""
    val = input(prompt).strip()
    return val if val else default


def input_yn(prompt, default=False):
    """布尔选项"""
    hint = ' [Y/n] ' if default else ' [y/N] '
    val = input(prompt + hint).strip().lower()
    if not val:
        return default
    return val in ('y', 'yes', '1')


def input_multiline(prompt):
    """多行输入，空行结束"""
    print(prompt + '（空行结束）:')
    lines = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line.strip())
    return lines


def print_header(title):
    print('\n' + '=' * 64)
    print(f'  {title}')
    print('=' * 64)


# ═══════════════════════════════════════════════════════
#  配置交互
# ═══════════════════════════════════════════════════════

def configure_crawler():
    """交互式配置 weibo-crawler"""
    print_header('配置 weibo-crawler')

    ids = input_multiline('用户ID（每行一个）:')
    if not ids:
        print('未输入用户ID，返回。')
        return None

    since = input_optional('起始日期 [YYYY-MM-DD/最近N天，默认 1900-01-01]: ', '1900-01-01')
    end = input_optional('结束日期 [YYYY-MM-DD，默认 当天]: ', '')

    print('\n输出模式:')
    print('  1) CSV  2) JSON  3) Markdown  4) SQLite  5) MySQL  6) Mongo  7) POST')
    modes_str = input_optional('多选用逗号分隔 [默认 csv,json]: ', 'csv,json')
    mode_map = {'1': 'csv', '2': 'json', '3': 'markdown', '4': 'sqlite',
                '5': 'mysql', '6': 'mongo', '7': 'post'}
    write_mode = [mode_map[m.strip()] for m in modes_str.split(',') if m.strip() in mode_map]
    if not write_mode:
        write_mode = ['csv', 'json']

    only_original = input_yn('仅爬取原创微博？', False)

    print('\n图片/视频下载:')
    orig_pic = input_yn('  原创微博图片？', False)
    retweet_pic = input_yn('  转发微博图片？', False)
    orig_video = input_yn('  原创微博视频？', False)
    retweet_video = input_yn('  转发微博视频？', False)
    avatar_dl = input_yn('  下载用户头像？', False)

    config = {
        'user_id_list': ids,
        'since_date': since,
        'end_date': end,
        'only_crawl_original': 1 if only_original else 0,
        'write_mode': write_mode,
        'original_pic_download': 1 if orig_pic else 0,
        'retweet_pic_download': 1 if retweet_pic else 0,
        'original_video_download': 1 if orig_video else 0,
        'retweet_video_download': 1 if retweet_video else 0,
        'avatar_download': 1 if avatar_dl else 0,
        'page_weibo_count': 20,
        'start_page': 1,
        'output_directory': 'weibo',
        'user_id_as_folder_name': 0,
        'remove_html_tag': 1,
    }
    return config


def configure_follow():
    """交互式配置 weibo-follow"""
    print_header('配置 weibo-follow')

    ids = input_multiline('用户ID（每行一个）:')
    if not ids:
        print('未输入用户ID，返回。')
        return None

    config = {'user_id_list': ids}
    return config


def configure_search():
    """交互式配置 weibo-search"""
    print_header('配置 weibo-search')

    keyword = input_required('关键词: ')
    start = input_optional('起始日期 [YYYY-MM-DD，默认 当天]: ', '')
    end = input_optional('结束日期 [YYYY-MM-DD，默认 当天]: ', '')

    print('\n微博类型: 1) 全部  2) 原创  3) 转发')
    search_type = input_optional('选择 [默认 1]: ', '1')

    config = {
        'keyword': keyword,
        'start_time': start,
        'end_time': end,
        'search_type': search_type,
    }
    return config


# ═══════════════════════════════════════════════════════
#  保存配置 & 运行
# ═══════════════════════════════════════════════════════

def save_config_json(module_name, config, config_filename='config.json'):
    """将配置写入对应模块目录的 JSON 文件"""
    cwd = APP_ROOT / module_name
    cwd.mkdir(parents=True, exist_ok=True)
    path = cwd / config_filename
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f'  配置已保存: {path}')
    return path


def run_module(module_name, config_filename='config.json'):
    """启动爬虫子进程，返回 PID"""
    cwd = APP_ROOT / module_name
    if not (cwd / config_filename).exists():
        print(f'  错误: 配置文件 {cwd / config_filename} 不存在，请先配置。')
        return None

    env = os.environ.copy()
    cookie = env.get('WEIBO_COOKIE', '')
    if not cookie:
        try:
            from utils import load_settings
            settings = load_settings()
            cookie = settings.get('cookie', '')
            if cookie:
                env['WEIBO_COOKIE'] = cookie
        except Exception:
            pass

    print(f'\n  启动 {module_name} ...')
    proc = subprocess.Popen(
        ['python3', 'run.py', '--config', str(cwd / config_filename)],
        cwd=cwd, env=env,
    )
    running_pids[module_name] = proc.pid
    print(f'  进程 PID: {proc.pid}')
    print(f'  查看日志: logs/{module_name}/')
    return proc.pid


def stop_module(module_name):
    """停止指定爬虫"""
    pid = running_pids.get(module_name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f'  已发送停止信号给 {module_name} (PID {pid})')
            del running_pids[module_name]
        except ProcessLookupError:
            print(f'  进程 {pid} 已结束。')
            del running_pids[module_name]
    else:
        print(f'  {module_name} 没有正在运行的进程。')


# ═══════════════════════════════════════════════════════
#  查看
# ═══════════════════════════════════════════════════════

def show_history():
    """显示执行历史"""
    print_header('执行历史')
    if not HISTORY_FILE.exists():
        print('  暂无历史记录。')
        return

    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        records = json.load(f)

    if not records:
        print('  暂无历史记录。')
        return

    records.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
    print(f'  {"状态":<8} {"类型":<18} {"摘要"}')
    print('  ' + '-' * 60)
    for r in records[:20]:
        status = r.get('status', '?')
        ctype = r.get('crawler_type', '?')
        summary = r.get('summary', '')[:60]
        print(f'  {status:<8} {ctype:<18} {summary}')
    print(f'\n  共 {len(records)} 条记录，显示最近 20 条。')


def show_logs():
    """显示日志"""
    print_header('日志文件')
    if not LOGS_DIR.exists():
        print('  日志目录不存在。')
        return

    for log_dir in sorted(LOGS_DIR.iterdir()):
        if log_dir.is_dir():
            log_files = sorted(log_dir.glob('*.log'), reverse=True)[:5]
            if log_files:
                print(f'\n  [{log_dir.name}]')
                for f in log_files:
                    size_kb = f.stat().st_size / 1024
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%m-%d %H:%M')
                    print(f'    {mtime}  {size_kb:>8.1f}KB  {f.name}')

    print()


def tail_log():
    """查看最新日志"""
    if not LOGS_DIR.exists():
        print('  日志目录不存在。')
        return

    all_logs = []
    for log_dir in LOGS_DIR.iterdir():
        if log_dir.is_dir():
            all_logs.extend(log_dir.glob('*.log'))
    all_logs.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    if not all_logs:
        print('  没有日志文件。')
        return

    print('\n  最近的日志文件:')
    for i, f in enumerate(all_logs[:5]):
        print(f'    {i+1}) {f.relative_to(LOGS_DIR)}')

    try:
        choice = int(input('\n  选择文件序号（回车取消）: ').strip() or '0')
        if 1 <= choice <= min(5, len(all_logs)):
            target = all_logs[choice - 1]
            lines = int(input_optional('  显示行数 [默认 50]: ', '50'))
            print(f'\n  --- {target.relative_to(LOGS_DIR)} (最后 {lines} 行) ---\n')
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    print(f'  {line.rstrip()}')
    except (ValueError, KeyboardInterrupt):
        pass


def show_settings():
    """显示全局设置"""
    print_header('全局设置')

    cookie = os.environ.get('WEIBO_COOKIE', '')
    try:
        from utils import load_settings
        settings = load_settings()
        cookie = settings.get('cookie', cookie)
        print(f'  Cookie:    {"已设置" if cookie else "未设置"}')
        print(f'  时区:      {settings.get("timezone", TZ)}')
        print(f'  日志级别:  {settings.get("log_settings", {}).get("level", "INFO")}')
        mysql = settings.get('mysql', {})
        print(f'  MySQL:     {"已配置" if mysql.get("host") else "未配置"}')
        mongo = settings.get('mongo', {})
        print(f'  MongoDB:   {"已配置" if mongo.get("uri") else "未配置"}')
        sqlite = settings.get('sqlite', {})
        print(f'  SQLite:    {"已启用" if sqlite.get("enabled") else "未启用"}')
    except Exception:
        print(f'  Cookie:    {"已设置" if cookie else "未设置 (可通过环境变量 WEIBO_COOKIE 设置)"}')

    print()


def show_status():
    """显示当前状态"""
    print_header('系统状态')
    print(f'  GUI 地址:    {GUI_URL}')
    print(f'  数据目录:    {DATA_DIR}')
    print(f'  日志目录:    {LOGS_DIR}')
    print(f'  运行中的爬虫: ', end='')
    if running_pids:
        for name, pid in running_pids.items():
            try:
                os.kill(pid, 0)
                print(f'{name}(PID:{pid}) ', end='')
            except OSError:
                pass
    else:
        print('无', end='')
    print()


MODULE_NAMES = {
    '1': 'weibo-crawler',
    '2': 'weibo-follow',
    '3': 'weibo-search',
}

CONFIGURATORS = {
    '1': configure_crawler,
    '2': configure_follow,
    '3': configure_search,
}

CONFIG_FILES = {
    '1': 'config.json',
    '2': 'config.json',
    '3': 'crawler_config.json',
}


# ═══════════════════════════════════════════════════════
#  主菜单
# ═══════════════════════════════════════════════════════

def main():
    while True:
        print_header('Harvester CLI 管理工具')
        print(f'  Web GUI: {GUI_URL}')
        print('')
        print('  ── 配置并运行 ──')
        print('  1. weibo-crawler（用户微博爬虫）')
        print('  2. weibo-follow（关注列表爬虫）')
        print('  3. weibo-search（关键词搜索爬虫）')
        print('')
        print('  ── 快速运行 ──（使用已有配置文件）')
        print('  q1. 运行 weibo-crawler')
        print('  q2. 运行 weibo-follow')
        print('  q3. 运行 weibo-search')
        print('')
        print('  ── 管理 ──')
        print('  h. 查看执行历史')
        print('  l. 查看日志文件')
        print('  t. 查看最新日志内容')
        print('  s. 查看全局设置')
        print('  i. 系统状态')
        print('')
        print('  ── 控制 ──')
        print('  stop1. 停止 crawler')
        print('  stop2. 停止 follow')
        print('  stop3. 停止 search')
        print('')
        print('  q. 退出')

        choice = input('\n请选择: ').strip().lower()

        # 配置并运行
        if choice in MODULE_NAMES:
            config = CONFIGURATORS[choice]()
            if config:
                save_config_json(MODULE_NAMES[choice], config, CONFIG_FILES[choice])
                if input_yn('\n是否立即运行？', True):
                    run_module(MODULE_NAMES[choice], CONFIG_FILES[choice])
            input('\n按回车继续...')

        # 快速运行
        elif choice in ('q1', 'q2', 'q3'):
            idx = choice[1]  # '1', '2', '3'
            name = MODULE_NAMES[idx]
            cfg = CONFIG_FILES[idx]
            if not (APP_ROOT / name / cfg).exists():
                print(f'  配置文件 {name}/{cfg} 不存在，请先配置（选 {idx}）。')
            else:
                run_module(name, cfg)
            input('\n按回车继续...')

        # 查看
        elif choice == 'h':
            show_history()
            input('\n按回车继续...')
        elif choice == 'l':
            show_logs()
            input('\n按回车继续...')
        elif choice == 't':
            tail_log()
            input('\n按回车继续...')
        elif choice == 's':
            show_settings()
            input('\n按回车继续...')
        elif choice == 'i':
            show_status()
            input('\n按回车继续...')

        # 停止
        elif choice == 'stop1':
            stop_module('weibo-crawler')
        elif choice == 'stop2':
            stop_module('weibo-follow')
        elif choice == 'stop3':
            stop_module('weibo-search')

        # 退出
        elif choice == 'q':
            # 清理子进程
            for name, pid in list(running_pids.items()):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            print('再见。')
            break

        else:
            print('无效选项，请重新输入。')
            input('\n按回车继续...')


if __name__ == '__main__':
    main()
