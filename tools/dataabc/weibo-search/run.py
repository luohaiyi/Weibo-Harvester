#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harvester weibo-search 包装入口
设置环境变量后启动 Scrapy，通过 os.chdir 管理输出路径（避免修改 pipelines.py）
"""

import argparse
import json
import os
import sys

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings


def main():
    parser = argparse.ArgumentParser(description="运行 weibo-search")
    parser.add_argument("--config", dest="config_path", default=None, help="配置文件路径")
    args = parser.parse_args()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    default_config_path = os.path.join(project_dir, "crawler_config.json")
    config_path = os.path.abspath(args.config_path) if args.config_path else default_config_path

    if not os.path.isfile(config_path):
        sys.exit(f"配置文件不存在：{config_path}")

    # 读取配置获取输出目录
    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)

    # 从环境变量注入 cookie（不落入磁盘文件）
    if 'cookie' not in config or not config['cookie']:
        cookie_from_env = os.environ.get('WEIBO_COOKIE', '')
        if cookie_from_env:
            config['cookie'] = cookie_from_env

    output_root = config.get('OUTPUT_ROOT', '/app/data/weibo-search')
    os.makedirs(output_root, exist_ok=True)

    # 确保项目目录在 sys.path 中（Scrapy 需要找到 weibo 包）
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    # 设置环境变量（必须在 get_project_settings() 之前）
    os.environ["WEIBO_SEARCH_CONFIG"] = config_path
    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "weibo.settings")

    # 切换工作目录到输出根目录（原始 pipelines.py 使用相对路径 '结果文件'）
    os.chdir(output_root)

    # 此时 sys.path 已有项目目录 + 环境变量已设 → Scrapy 可正常初始化
    from weibo.spiders.search import SearchSpider

    settings = get_project_settings()
    process = CrawlerProcess(settings)
    process.crawl(SearchSpider)
    process.start()


if __name__ == "__main__":
    main()
