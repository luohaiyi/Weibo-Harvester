#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harvester weibo-crawler 包装入口
不修改原始 weibo.py，通过导入 Weibo 类 + argparse 实现配置注入
"""

import argparse
import datetime
import json
import os
import sys
from urllib.parse import urlparse

import json5

from weibo import Weibo
import const
from util.notify import push_deer


def main():
    parser = argparse.ArgumentParser(description="运行 weibo-crawler")
    parser.add_argument("--config", dest="config_path", default=None, help="配置文件路径")
    args = parser.parse_args()

    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    config_path = os.path.abspath(args.config_path) if args.config_path else default_path

    if not os.path.isfile(config_path):
        sys.exit(f"配置文件不存在：{config_path}")

    with open(config_path, encoding="utf-8") as f:
        config_content = f.read()
        try:
            config = json5.loads(config_content)
        except Exception:
            config = json.loads(config_content)

    # 从环境变量注入 cookie（不落入磁盘文件）
    if 'cookie' not in config or not config['cookie']:
        cookie_from_env = os.environ.get('WEIBO_COOKIE', '')
        if cookie_from_env:
            config['cookie'] = cookie_from_env

    # 兼容旧字段名
    for old, new in [("filter", "only_crawl_original"), ("result_dir_name", "user_id_as_folder_name")]:
        if old in config and new not in config:
            config[new] = config.pop(old)

    try:
        wb = Weibo(config)
        wb.start()

        # 下载用户头像（需在 config.json 中设置 "avatar_download": 1）
        if config.get("avatar_download", 0):
            _download_avatar(wb)

        if const.NOTIFY["NOTIFY"]:
            push_deer("更新了一次微博")
    except Exception as e:
        if const.NOTIFY["NOTIFY"]:
            push_deer(f"weibo-crawler运行出错，错误为{e}")
        import logging
        logging.getLogger("weibo").exception(e)


def _download_avatar(wb):
    """
    为本次爬取的所有用户下载头像到各自的用户文件夹。
    从本次 config 的 user_config_list 获取用户 ID 列表，
    再到 users.csv 中匹配对应用户的 avatar_hd / profile_image_url，
    复用 Weibo 实例的 download_one_file，继承全部校验/重试/EXIF 逻辑。
    文件名格式：avatar_<用户ID>_<UTC时间>.后缀
    """
    import csv

    # 本次爬取的用户 ID 集合
    current_ids = {str(uc["user_id"]) for uc in wb.user_config_list}
    if not current_ids:
        print("[头像] 本次无用户 ID，跳过")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, wb.output_directory, "users.csv")

    if not os.path.isfile(csv_path):
        print("[头像] users.csv 不存在，跳过全部头像下载")
        return

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = list(csv.reader(f))
    if len(reader) < 2:
        print("[头像] users.csv 无用户数据，跳过")
        return

    # CSV 列：0=用户id  1=昵称 ... 15=头像(profile_image_url)  16=高清头像(avatar_hd)
    rows = reader[1:]  # 跳过表头
    output_base = os.path.join(script_dir, wb.output_directory)
    utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    success = 0
    skipped = 0

    for row in rows:
        if len(row) <= 16:
            continue

        user_id = row[0].strip()
        # 只处理本次爬取的用户
        if user_id not in current_ids:
            continue

        screen_name = row[1].strip()
        # 优先高清头像，其次普通头像
        avatar_url = row[16].strip() or row[15].strip()

        if not avatar_url:
            skipped += 1
            print(f"[头像] {screen_name}({user_id}) 无头像 URL，跳过")
            continue

        # 确定用户文件夹名（遵循 user_id_as_folder_name 配置）
        dir_name = str(user_id) if wb.user_id_as_folder_name else screen_name
        user_dir = os.path.join(output_base, dir_name)
        os.makedirs(user_dir, exist_ok=True)

        # 提取文件扩展名
        _, ext = os.path.splitext(urlparse(avatar_url).path)
        if not ext or len(ext) > 5:
            ext = ".jpg"

        filename = f"avatar_{user_id}_{utc_now}{ext}"
        avatar_path = os.path.join(user_dir, filename)

        print(f"[头像] {screen_name}({user_id}): {avatar_url[:60]}... → {filename}")
        wb.download_one_file(
            avatar_url, avatar_path, "img", user_id, ""
        )
        success += 1

    print(f"[头像] 完成: 成功 {success}, 跳过(无URL) {skipped}, "
          f"本次用户 {len(current_ids)} 个")


if __name__ == "__main__":
    main()
