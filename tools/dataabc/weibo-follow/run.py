#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harvester weibo-follow 包装入口
通过子类覆写 write_to_txt() 实现动态输出路径 + 三数据库写入
不修改原始 weibo_follow.py
"""

import argparse
import json
import os
import sys
from datetime import datetime

from weibo_follow import Follow


class HarvesterFollow(Follow):
    """继承原始 Follow 类，扩展数据库写入能力"""

    def __init__(self, config):
        super().__init__(config)
        self._config = config

        # 数据库连接句柄（惰性初始化）
        self._sqlite_conn = None
        self._mysql_conn = None
        self._mongo_client = None

    # ================================================================
    # 数据库初始化
    # ================================================================

    def _init_databases(self):
        """根据配置初始化启用的数据库连接"""
        if self._config.get('use_sqlite'):
            try:
                self._init_sqlite()
                print("SQLite 数据库初始化成功")
            except Exception as e:
                print(f"SQLite 初始化失败，将跳过 SQLite 写入: {e}")

        if self._config.get('use_mysql'):
            try:
                self._init_mysql()
                print("MySQL 数据库初始化成功")
            except Exception as e:
                print(f"MySQL 初始化失败，将跳过 MySQL 写入: {e}")

        if self._config.get('use_mongo'):
            try:
                self._init_mongo()
                print("MongoDB 数据库初始化成功")
            except Exception as e:
                print(f"MongoDB 初始化失败，将跳过 MongoDB 写入: {e}")

    def _close_databases(self):
        """安全关闭所有数据库连接"""
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
        if self._mysql_conn:
            try:
                self._mysql_conn.close()
            except Exception:
                pass
        if self._mongo_client:
            try:
                self._mongo_client.close()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # SQLite
    # ----------------------------------------------------------------

    def _init_sqlite(self):
        import sqlite3

        db_path = self._config.get('sqlite_db_path') or os.path.join(
            os.environ.get('SQLITE_DATA_DIR', '/app/data/sqlite'), 'weibo_follow.db')
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._sqlite_conn = sqlite3.connect(db_path)
        # 后续游标复用，设置较短的 busy_timeout
        self._sqlite_conn.execute("PRAGMA journal_mode=WAL")
        self._sqlite_conn.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                id            TEXT PRIMARY KEY,
                source_user_id TEXT NOT NULL,
                follow_uri    TEXT NOT NULL,
                follow_nickname TEXT,
                crawled_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._sqlite_conn.commit()

    def _write_sqlite(self, entry):
        if not self._sqlite_conn:
            return
        try:
            self._sqlite_conn.execute(
                "INSERT OR REPLACE INTO follows (id, source_user_id, follow_uri, follow_nickname, crawled_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (f"{self.user_id}_{entry['uri']}", self.user_id,
                 entry['uri'], entry['nickname'])
            )
            self._sqlite_conn.commit()
        except Exception as e:
            print(f"SQLite 写入失败: {e}")
            try:
                self._sqlite_conn.rollback()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # MySQL
    # ----------------------------------------------------------------

    def _init_mysql(self):
        import pymysql

        mysql_config = self._config.get('mysql_config', {})
        self._mysql_db_name = mysql_config.get('database', 'weibo_harvester')
        self._mysql_conn = pymysql.connect(
            host=mysql_config.get('host', 'localhost'),
            port=mysql_config.get('port', 3306),
            user=mysql_config.get('user', 'root'),
            password=mysql_config.get('password', ''),
            charset='utf8mb4'
        )
        cursor = self._mysql_conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {self._mysql_db_name} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        self._mysql_conn.select_db(self._mysql_db_name)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                id              VARCHAR(50) PRIMARY KEY,
                source_user_id  VARCHAR(20) NOT NULL,
                follow_uri      VARCHAR(20) NOT NULL,
                follow_nickname VARCHAR(100),
                crawled_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_source (source_user_id),
                INDEX idx_follow (follow_uri)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        self._mysql_conn.commit()

    def _write_mysql(self, entry):
        if not self._mysql_conn:
            return
        try:
            sql = """INSERT INTO follows (id, source_user_id, follow_uri, follow_nickname, crawled_at)
                     VALUES (%s, %s, %s, %s, NOW())
                     ON DUPLICATE KEY UPDATE follow_nickname=VALUES(follow_nickname), crawled_at=NOW()"""
            cursor = self._mysql_conn.cursor()
            cursor.execute(sql, (
                f"{self.user_id}_{entry['uri']}", self.user_id,
                entry['uri'], entry['nickname']
            ))
            self._mysql_conn.commit()
        except Exception as e:
            print(f"MySQL 写入失败: {e}")
            try:
                self._mysql_conn.rollback()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # MongoDB
    # ----------------------------------------------------------------

    def _init_mongo(self):
        from pymongo import MongoClient

        mongo_uri = self._config.get('mongodb_URI') or os.environ.get(
            'MONGODB_URI', 'mongodb://weibo-mongo:27017/')
        self._mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        # 测试连接
        self._mongo_client.admin.command('ping')
        self._mongo_collection = self._mongo_client[self._mysql_db_name]['follows']

    def _write_mongo(self, entry):
        if not self._mongo_client:
            return
        try:
            doc = {
                'source_user_id': self.user_id,
                'follow_uri': entry['uri'],
                'follow_nickname': entry['nickname'],
                'crawled_at': datetime.now(),
            }
            self._mongo_collection.update_one(
                {'source_user_id': self.user_id, 'follow_uri': entry['uri']},
                {'$set': doc},
                upsert=True
            )
        except Exception as e:
            print(f"MongoDB 写入失败: {e}")

    # ================================================================
    # 输出逻辑
    # ================================================================

    def write_to_txt(self):
        """输出 TXT 文件 + 数据库（根据配置）"""
        # ---- TXT 文件 ----
        output_filename = self._config.get('output_filename', 'user_id_list.txt')
        output_dir = os.path.dirname(os.path.abspath(output_filename))
        if output_dir and not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        with open(output_filename, 'ab') as f:
            for user in self.follow_list:
                f.write((user['uri'] + ' ' + user['nickname'] + '\n').encode(
                    sys.stdout.encoding))

        # ---- 数据库写入 ----
        for entry in self.follow_list:
            self._write_sqlite(entry)
            self._write_mysql(entry)
            self._write_mongo(entry)

    def start(self):
        """运行爬虫（带数据库生命周期管理）"""
        try:
            self._init_databases()
            for user_id in self.user_id_list:
                self.initialize_info(user_id)
                print('*' * 100)
                self.get_follow_list()
                self.write_to_txt()
                print('信息抓取完毕')
                print('*' * 100)
        except Exception as e:
            print('Error: ', e)
            import traceback
            traceback.print_exc()
        finally:
            self._close_databases()


def main():
    parser = argparse.ArgumentParser(description="运行 weibo-follow")
    parser.add_argument("--config", dest="config_path", default=None, help="配置文件路径")
    args = parser.parse_args()

    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    config_path = os.path.abspath(args.config_path) if args.config_path else default_path

    if not os.path.isfile(config_path):
        sys.exit(f"配置文件不存在：{config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.loads(f.read())

    # 从环境变量注入 cookie（不落入磁盘文件）
    if 'cookie' not in config or not config['cookie']:
        cookie_from_env = os.environ.get('WEIBO_COOKIE', '')
        if cookie_from_env:
            config['cookie'] = cookie_from_env

    wb = HarvesterFollow(config)
    wb.start()


if __name__ == "__main__":
    main()
