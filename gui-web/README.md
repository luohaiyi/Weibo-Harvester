# 微博爬虫 GUI

本模块是 WeiboHarvester 的统一控制面。

它不是一个孤立的小网页，而是当前整个项目的**主入口**：参数填写、任务启动、运行状态、历史记录、日志查看，都从这里收口。

---

## 当前定位

GUI 负责做 4 件事：

1. 提供三个功能模块的统一配置界面
2. 为每次运行生成唯一配置文件
3. 调度真实模块入口执行并跟踪状态
4. 持久化历史、失败原因、日志文件和输出目标

当前已经不是“待开发页面”，而是项目实际使用中的控制台。

---

## 推荐启动方式

本项目约定：**服务在 Docker 容器内运行，宿主机不直接跑正式流程。**

在仓库根目录执行：

```bash
docker compose up -d
```

访问：

```text
http://localhost:5100
```

如果镜像或依赖有明显变更，再用：

```bash
docker compose up -d --build
```

---

## 页面结构

顶部导航包含 6 个入口：

- 首页
- weibo-crawler
- weibo-follow
- weibo-search
- 日志管理
- 全局设置

### 首页

- 查看运行状态
- 查看历史记录
- 筛选不同爬虫类型与状态
- 直接对历史记录执行再次运行、删除、查看日志等动作

### 三个功能页面

- 填写各自参数
- 启动任务
- 停止任务
- 从历史回填参数继续运行

### 日志管理

- 查看各模块日志文件
- 按文件查看日志内容
- 删除单个日志或清空日志

### 全局设置

- 存储 Cookie
- 存储 MySQL 配置
- 管理日志级别、历史保留等全局参数

---

## 配置驱动运行机制

这是当前 GUI 最重要的设计点。

### 旧方式的问题

旧方案会把表单参数直接覆写到各模块固定配置文件里，副作用很重：

- 多次运行互相覆盖
- 历史记录难以精准回放
- 删除历史无法联动删除配置
- 模块入口协议不统一

### 当前方式

每次点击“开始运行”时，GUI 会：

1. 生成唯一 JSON 配置文件
2. 保存到 `/app/temp/gui-web/runtime-configs/<crawler>/`
3. 调用模块入口并传入 `--config <path>`
4. 创建一条 `running` 状态的历史记录
5. 进程结束后由监控逻辑统一回写最终状态

三个模块当前都已支持配置路径启动：

- `weibo-crawler/run.py --config <path>`
- `weibo-follow/run.py --config <path>`
- `weibo-search/run.py --config <path>`

---

## 运行时目录

GUI 自身不再把运行时文件写回源码目录，而是统一写到父级挂载目录。

### GUI 临时目录

宿主机：`./temp/gui-web/`  
容器内：`/app/temp/gui-web/`

包含：

- `settings.json`
- `status.json`
- `history.json`
- `runtime-configs/`

### 日志目录

宿主机：`./logs/`  
容器内：`/app/logs/`

按模块分类：

- `/app/logs/gui-web`
- `/app/logs/weibo-crawler`
- `/app/logs/weibo-follow`
- `/app/logs/weibo-search`

---

## 核心数据模型

### status.json

表示当前是否有任务在运行，例如：

```json
{
  "running_crawler": "weibo-crawler",
  "pid": 12345,
  "history_id": "...",
  "log_filename": "crawler_2026-04-05_12-16-18.log"
}
```

### history.json

当前历史记录不再保存完整表单快照为主，而是围绕“可追踪运行”组织字段。核心字段包括：

- `id`
- `crawler_type`
- `timestamp`
- `finished_at`
- `status`
- `duration`
- `config_file`
- `summary`
- `log_filename`
- `exit_code`
- `failure_reason`
- `stop_requested`
- `output_targets`

### runtime-configs/

保存每次运行生成的唯一配置文件，按模块分目录：

- `weibo-crawler/`
- `weibo-follow/`
- `weibo-search/`

删除历史记录时，会联动删除对应配置文件。

---

## 项目结构

```text
gui-web/
├── app.py                 # Flask API 与任务调度入口
├── config.py              # 路径与常量定义
├── utils.py               # 历史/日志/配置文件工具函数
├── requirements.txt       # Python 依赖
├── README.md              # 当前文档
├── 需求规格说明书.md       # 设计与实现说明
├── harvesters/            # 三个模块的配置生成逻辑
│   ├── weibo_crawler.py
│   ├── weibo_follow.py
│   └── weibo_search.py
├── templates/
│   └── index.html         # Vue 页面模板
└── static/
    ├── css/style.css
    ├── js/app.js
    └── element-plus/
```

---

## 注意事项

1. Cookie 保存在 `/app/temp/gui-web/settings.json`，不要对外分享
2. 停止任务时会先写入 `stop_requested=True`，最终状态由监控线程统一收口
3. 历史记录中的配置文件、失败原因、输出目标、日志文件名都属于一等信息，不要再退回只有“成功/失败”两个字的粗糙模型
4. 纯浏览器端加载 Vue + Element Plus 时，自定义组件必须使用显式闭合标签，不能写自闭合标签

---

## 建议把哪些文档当真

- **项目整体怎么启动、怎么跑**：看项目根目录下的 `document/README.md`
- **GUI 现在怎么工作、数据结构与设计口径**：看这份 `gui-web/README.md`
- **完整的 API 接口参考**：看 `document/README.md` 中的 API 接口说明章节
- **单模块参数细节**：看各模块自己的 `README.md`（位于 `tools/dataabc/weibo-*/`）
