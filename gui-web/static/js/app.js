const { createApp, ref, reactive, computed, onMounted, watch } = Vue;

// ---- 工具函数 ----

/**
 * 带重试的 fetch 封装，自动重试 + 指数退避 + 超时
 */
async function fetchWithRetry(url, options = {}, retries = 2, timeoutMs = 15000) {
    const { timeout: optTimeout, ...fetchOptions } = options;
    const effectiveTimeout = optTimeout || timeoutMs;

    for (let attempt = 0; attempt <= retries; attempt++) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), effectiveTimeout);
        try {
            const response = await axios({
                url,
                ...fetchOptions,
                signal: controller.signal,
            });
            clearTimeout(timer);
            return response;
        } catch (error) {
            clearTimeout(timer);
            if (attempt < retries && (error.code === 'ECONNABORTED' || !error.response || error.response.status >= 500)) {
                const delay = Math.min(1000 * Math.pow(2, attempt), 8000);
                console.warn(`Request to ${url} failed (attempt ${attempt + 1}/${retries + 1}), retrying in ${delay}ms`);
                await new Promise(resolve => setTimeout(resolve, delay));
                continue;
            }
            throw error;
        }
    }
}

/**
 * JSON 安全的 localStorage 存取
 */
const storage = {
    get(key, fallback = null) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch { return fallback; }
    },
    set(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota exceeded */ }
    },
};

/**
 * 将 reactive 对象的非函数字段持久化到 localStorage
 */
function persistReactive(key, obj) {
    const plain = {};
    for (const [k, v] of Object.entries(obj)) {
        if (typeof v !== 'function') plain[k] = v;
    }
    storage.set(key, plain);
}

/**
 * Deep watch 自动持久化
 */
function autoPersist(key, obj) {
    watch(obj, () => persistReactive(key, obj), { deep: true });
}


const app = createApp({
    setup() {
        // 状态
        const activeMenu = ref('home');
        const loading = ref(false);
        // 每个爬虫独立的状态跟踪
        const runningCrawlers = reactive({
            'weibo-crawler': false,
            'weibo-follow': false,
            'weibo-search': false
        });
        const history = ref([]);
        const logFiles = ref([]);
        
        // 筛选和分页
        const historyFilter = reactive({
            type: '',
            status: ''
        });
        
        const pagination = reactive({
            currentPage: 1,
            pageSize: 20
        });
        
        // 配置 —— 键名规范：功能前缀-参数名
        const crawlerConfig = reactive({
            // 基本爬取配置
            'crawler-user_id_list': '',
            'crawler-only_crawl_original': true,
            'crawler-query_list': '',
            'crawler-since_date': '',
            'crawler-end_date': '',
            'crawler-start_page': 1,
            'crawler-page_weibo_count': 20,
            // 输出配置
            'crawler-write_mode_csv': true,
            'crawler-write_mode_json': false,
            'crawler-write_mode_markdown': false,
            'crawler-write_mode_sqlite': false,
            'crawler-write_mode_mysql': false,
            'crawler-write_mode_mongo': false,
            'crawler-write_mode_post': false,
            'crawler-markdown_split_by': 'day_by_month',
            'crawler-output_directory': '/app/data/weibo-crawler',
            'crawler-user_id_as_folder_name': false,
            'crawler-remove_html_tag': true,
            // 图片/视频下载
            'crawler-original_pic_download': false,
            'crawler-retweet_pic_download': false,
            'crawler-original_video_download': false,
            'crawler-retweet_video_download': false,
            'crawler-original_live_photo_download': false,
            'crawler-retweet_live_photo_download': false,
            'crawler-avatar_download': false,
            'crawler-write_time_in_exif': true,
            'crawler-change_file_time': true,
            // 评论与转发下载
            'crawler-download_comment': false,
            'crawler-comment_max_download_count': 100,
            'crawler-comment_pic_download': false,
            'crawler-download_repost': false,
            'crawler-repost_max_download_count': 100,
            // 数据库配置
            'crawler-store_binary_in_sqlite': false,
            'crawler-post_config_url': '',
            'crawler-post_config_token': '',
            // 反封禁配置
            'crawler-anti_ban_enabled': true,
            'crawler-anti_ban_max_weibo_per_session': 500,
            'crawler-anti_ban_batch_size': 50,
            'crawler-anti_ban_batch_delay': 30,
            'crawler-anti_ban_request_delay_min': 8,
            'crawler-anti_ban_request_delay_max': 15,
            'crawler-anti_ban_max_session_time': 600,
            'crawler-anti_ban_max_api_errors': 5,
            'crawler-anti_ban_rest_time_min': 180,
            'crawler-anti_ban_random_rest_probability': 0.01
        });
        
        const followConfig = reactive({
            'follow-user_id_list': '',
            'follow-use_sqlite': false,
            'follow-use_mysql': false,
            'follow-use_mongo': false
        });
        
        const searchConfig = reactive({
            // 关键词
            'search-keyword': '',
            // 时间范围
            'search-start_time': '',
            'search-end_time': '',
            // 微博类型 (0-6)
            'search-search_type': '1',
            // 包含内容 (0-4)
            'search-filter_type': '0',
            // 排序方式 (暂未使用)
            'search-sort_type': '1',
            // 地区（文本输入，多个用逗号分隔）
            'search-region': '全部',
            // 进一步搜索阈值 (40-50)
            'search-further_threshold': 46,
            // 结果数量限制 (0为不限制)
            'search-limit_result': 0,
            // 最大页数
            'search-max_pages': 100,
            // 下载延迟（秒）
            'search-wait_time': 5,
            // 存储路径
            'search-images_store': '/app/data/weibo-search/images',
            'search-files_store': '/app/data/weibo-search/files',
            // 输出选项
            'search-use_csv': true,
            'search-use_mysql': false,
            'search-use_mongo': false,
            'search-use_sqlite': false,
            'search-use_images': false,
            'search-use_videos': false
        });
        
        const settings = reactive({
            cookie: '',
            cookie_tested: false,
            cookie_test_status: '',  // '' | 'success' | 'fail'
            timezone: 'Asia/Shanghai',  // 默认时区
            // MySQL 配置
            mysql_enabled: false,
            mysql_default: false,
            mysql_tested: false,
            mysql_test_status: '',  // '' | 'success' | 'fail'
            mysql_host: 'localhost',
            mysql_port: 3306,
            mysql_database: 'weibo',
            mysql_user: 'root',
            mysql_password: '',
            // MongoDB 配置
            mongo_enabled: false,
            mongo_default: false,
            mongo_tested: false,
            mongo_test_status: '',
            mongo_uri: 'mongodb://weibo-mongo:27017/',
            // SQLite 配置
            sqlite_enabled: false,
            sqlite_default: false,
            sqlite_tested: false,
            sqlite_test_status: '',
            sqlite_db_path: '/app/data/sqlite/weibodata.db',
            log_level: 'INFO',
            log_keep_count: 100
        });
        
        // 测试状态
        const testing = reactive({
            cookie: false,
            mysql: false,
            mongo: false,
            sqlite: false
        });
        
        // 对话框
        const logDialog = reactive({
            visible: false,
            content: ''
        });
        
        const confirmDialog = reactive({
            visible: false,
            message: '',
            onConfirm: null
        });
        
        // 功能卡片
        const featureCards = [
            { key: 'weibo-crawler', title: 'weibo-crawler', desc: '爬取指定用户的微博数据', icon: 'Document', color: '#409EFF' },
            { key: 'weibo-follow', title: 'weibo-follow', desc: '获取用户的关注列表', icon: 'User', color: '#67C23A' },
            { key: 'weibo-search', title: 'weibo-search', desc: '按关键词搜索微博', icon: 'Search', color: '#E6A23C' }
        ];
        
        // 计算属性
        const filteredHistory = computed(() => {
            let result = history.value;
            if (historyFilter.type) {
                result = result.filter(h => h.crawler_name === historyFilter.type);
            }
            if (historyFilter.status) {
                result = result.filter(h => h.status === historyFilter.status);
            }
            return result;
        });
        
        const paginatedHistory = computed(() => {
            const start = (pagination.currentPage - 1) * pagination.pageSize;
            const end = start + pagination.pageSize;
            return filteredHistory.value.slice(start, end);
        });
        
        // 方法
        const handleMenuSelect = (index) => {
            activeMenu.value = index;
            if (index === 'home') {
                loadHistory();
            } else if (index === 'logs') {
                loadLogFiles();
            } else if (index === 'settings') {
                loadSettings();
            }
        };
        
        const navigateTo = (key) => {
            activeMenu.value = key;
        };
        
        const formatTime = (timeStr) => {
            if (!timeStr) return '-';
            const date = new Date(timeStr);
            const now = new Date();
            const isToday = date.toDateString() === now.toDateString();
            const isYesterday = new Date(now - 86400000).toDateString() === date.toDateString();
            
            const timeWithSeconds = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            
            if (isToday) {
                return `今天 ${timeWithSeconds}`;
            } else if (isYesterday) {
                return `昨天 ${timeWithSeconds}`;
            } else {
                return date.toLocaleString('zh-CN');
            }
        };
        
        const getCrawlerType = (name) => {
            const map = {
                'weibo-crawler': 'primary',
                'weibo-follow': 'success',
                'weibo-search': 'warning'
            };
            return map[name] || 'info';
        };

        const getCrawlerShortName = (name) => {
            const map = {
                'weibo-crawler': 'crawler',
                'weibo-follow': 'follow',
                'weibo-search': 'search'
            };
            return map[name] || name || '-';
        };

        const getHistorySummary = (row) => {
            if (!row) return '-';
            if (row.status === 'running') return '正在运行...';
            return row.summary || '-';
        };

        const getHistoryExtraInfo = (row) => {
            if (!row) return [];

            const details = [];
            if (row.config_file) details.push(`配置：${row.config_file}`);
            if (row.output_targets && row.output_targets.length) details.push(`输出：${row.output_targets.join('，')}`);
            if (row.failure_reason) details.push(`原因：${row.failure_reason}`);
            if (row.exit_code !== null && row.exit_code !== undefined) details.push(`退出码：${row.exit_code}`);
            if (row.log_filename) details.push(`日志：${row.log_filename}`);
            return details;
        };

        const hasHistoryExtraInfo = (row) => getHistoryExtraInfo(row).length > 0;
        
        const getStatusType = (status) => {
            const map = {
                'running': 'primary',
                'success': 'success',
                'failed': 'danger',
                'stopped': 'warning'
            };
            return map[status] || 'info';
        };
        
        const getStatusText = (status) => {
            const map = {
                'running': '运行中',
                'success': '成功',
                'failed': '失败',
                'stopped': '已停止'
            };
            return map[status] || status;
        };

        const handleSortChange = ({ prop, order }) => {
            const rows = [...history.value];
            if (!prop || !order) {
                history.value = rows.sort((a, b) => new Date(b.start_time || 0) - new Date(a.start_time || 0));
                return;
            }

            const direction = order === 'ascending' ? 1 : -1;
            history.value = rows.sort((a, b) => {
                const left = new Date(a[prop] || 0).getTime();
                const right = new Date(b[prop] || 0).getTime();
                return (left - right) * direction;
            });
        };

        const getLatestHistoryRecord = (crawlerName) => {
            return history.value.find(item => (item.crawler_name || item.crawler_type) === crawlerName) || null;
        };
        
        const loadHistory = async () => {
            try {
                const response = await fetchWithRetry('/api/history');
                history.value = [...response.data].sort((a, b) => new Date(b.start_time || 0) - new Date(a.start_time || 0));
            } catch (error) {
                ElementPlus.ElMessage.error('加载历史记录失败');
            }
        };
        
        const loadLogFiles = async () => {
            try {
                const response = await fetchWithRetry('/api/logs');
                logFiles.value = response.data;
            } catch (error) {
                ElementPlus.ElMessage.error('加载日志列表失败');
            }
        };
        
        const loadSettings = async () => {
            try {
                const response = await fetchWithRetry('/api/settings');
                const data = response.data;
                // 通用字段
                const knownKeys = ['cookie', 'timezone'];
                for (const key of knownKeys) {
                    if (key in data) settings[key] = data[key];
                }
                // MySQL 配置
                if (data.mysql_config) {
                    settings.mysql_enabled = data.mysql_config.enabled || false;
                    settings.mysql_default = data.mysql_config.default_enabled || false;
                    settings.mysql_host = data.mysql_config.host || 'localhost';
                    settings.mysql_port = data.mysql_config.port || 3306;
                    settings.mysql_user = data.mysql_config.user || 'root';
                    settings.mysql_password = data.mysql_config.password || '';
                    settings.mysql_database = data.mysql_config.database || 'weibo';
                }
                // MongoDB 配置
                if (data.mongo_config) {
                    settings.mongo_enabled = data.mongo_config.enabled || false;
                    settings.mongo_default = data.mongo_config.default_enabled || false;
                    settings.mongo_uri = data.mongo_config.uri || 'mongodb://weibo-mongo:27017/';
                }
                // SQLite 配置
                if (data.sqlite_config) {
                    settings.sqlite_enabled = data.sqlite_config.enabled || false;
                    settings.sqlite_default = data.sqlite_config.default_enabled || false;
                    settings.sqlite_db_path = data.sqlite_config.db_path || '/app/data/sqlite/weibodata.db';
                }
                // 日志设置
                if (data.log_settings) {
                    settings.log_level = data.log_settings.level || 'INFO';
                    settings.log_keep_count = data.log_settings.max_keep || 100;
                }
            } catch (error) {
                ElementPlus.ElMessage.error('加载设置失败');
            }
        };
        
        // 日期校验辅助函数
        const checkDateRange = async (startDate, endDate) => {
            if (startDate && endDate && startDate > endDate) {
                try {
                    await ElementPlus.ElMessageBox.confirm(
                        '起始日期晚于结束日期，将无法执行爬取任务，是否继续运行？',
                        '日期范围警告',
                        {
                            confirmButtonText: '继续运行',
                            cancelButtonText: '返回修改',
                            type: 'warning',
                            distinguishCancelAndClose: true,
                        }
                    );
                    return true; // 用户选择继续
                } catch {
                    return false; // 用户选择返回或关闭弹窗
                }
            }
            return true; // 日期合法，继续
        };

        const startCrawler = async (crawlerName) => {
            if (runningCrawlers[crawlerName]) {
                ElementPlus.ElMessage.warning('该爬虫正在运行');
                return;
            }
            
            let config;
            if (crawlerName === 'weibo-crawler') {
                if (!crawlerConfig['crawler-user_id_list'].trim()) {
                    ElementPlus.ElMessage.error('请输入用户ID');
                    return;
                }
                // 校验日期范围
                if (!(await checkDateRange(
                    crawlerConfig['crawler-since_date'],
                    crawlerConfig['crawler-end_date']
                ))) return;
                // 构建 write_mode 数组（后端用原始键名）
                const write_mode = [];
                if (crawlerConfig['crawler-write_mode_csv']) write_mode.push('csv');
                if (crawlerConfig['crawler-write_mode_json']) write_mode.push('json');
                if (crawlerConfig['crawler-write_mode_markdown']) write_mode.push('markdown');
                if (crawlerConfig['crawler-write_mode_sqlite']) write_mode.push('sqlite');
                if (crawlerConfig['crawler-write_mode_mysql']) write_mode.push('mysql');
                if (crawlerConfig['crawler-write_mode_mongo']) write_mode.push('mongo');
                if (crawlerConfig['crawler-write_mode_post']) write_mode.push('post');
                // 构建 query_list
                const query_list = crawlerConfig['crawler-query_list']
                    ? crawlerConfig['crawler-query_list'].split(',').map(s => s.trim()).filter(Boolean)
                    : [];
                // 发给后端的 params 使用原始键名（spider 的 params.get("xxx") 直接读取）
                config = {
                    user_id_list: crawlerConfig['crawler-user_id_list'].split('\n').filter(id => id.trim()),
                    only_crawl_original: crawlerConfig['crawler-only_crawl_original'] ? 1 : 0,
                    query_list: query_list,
                    since_date: crawlerConfig['crawler-since_date'] || '1900-01-01',
                    end_date: crawlerConfig['crawler-end_date'] || '',
                    start_page: crawlerConfig['crawler-start_page'],
                    page_weibo_count: crawlerConfig['crawler-page_weibo_count'],
                    write_mode: write_mode.length ? write_mode : ['csv'],
                    markdown_split_by: crawlerConfig['crawler-markdown_split_by'],
                    output_directory: crawlerConfig['crawler-output_directory'] || '/app/data/weibo-crawler',
                    user_id_as_folder_name: crawlerConfig['crawler-user_id_as_folder_name'] ? 1 : 0,
                    remove_html_tag: crawlerConfig['crawler-remove_html_tag'] ? 1 : 0,
                    original_pic_download: crawlerConfig['crawler-original_pic_download'] ? 1 : 0,
                    retweet_pic_download: crawlerConfig['crawler-retweet_pic_download'] ? 1 : 0,
                    original_video_download: crawlerConfig['crawler-original_video_download'] ? 1 : 0,
                    retweet_video_download: crawlerConfig['crawler-retweet_video_download'] ? 1 : 0,
                    original_live_photo_download: crawlerConfig['crawler-original_live_photo_download'] ? 1 : 0,
                    retweet_live_photo_download: crawlerConfig['crawler-retweet_live_photo_download'] ? 1 : 0,
                    avatar_download: crawlerConfig['crawler-avatar_download'] ? 1 : 0,
                    write_time_in_exif: crawlerConfig['crawler-write_time_in_exif'] ? 1 : 0,
                    change_file_time: crawlerConfig['crawler-change_file_time'] ? 1 : 0,
                    download_comment: crawlerConfig['crawler-download_comment'] ? 1 : 0,
                    comment_max_download_count: crawlerConfig['crawler-comment_max_download_count'],
                    comment_pic_download: crawlerConfig['crawler-comment_pic_download'] ? 1 : 0,
                    download_repost: crawlerConfig['crawler-download_repost'] ? 1 : 0,
                    repost_max_download_count: crawlerConfig['crawler-repost_max_download_count'],
                    store_binary_in_sqlite: crawlerConfig['crawler-store_binary_in_sqlite'] ? 1 : 0,
                    post_config: {
                        api_url: crawlerConfig['crawler-post_config_url'] || '',
                        api_token: crawlerConfig['crawler-post_config_token'] || ''
                    },
                    anti_ban_config: {
                        enabled: crawlerConfig['crawler-anti_ban_enabled'],
                        max_weibo_per_session: crawlerConfig['crawler-anti_ban_max_weibo_per_session'],
                        batch_size: crawlerConfig['crawler-anti_ban_batch_size'],
                        batch_delay: crawlerConfig['crawler-anti_ban_batch_delay'],
                        request_delay_min: crawlerConfig['crawler-anti_ban_request_delay_min'],
                        request_delay_max: crawlerConfig['crawler-anti_ban_request_delay_max'],
                        max_session_time: crawlerConfig['crawler-anti_ban_max_session_time'],
                        max_api_errors: crawlerConfig['crawler-anti_ban_max_api_errors'],
                        rest_time_min: crawlerConfig['crawler-anti_ban_rest_time_min'],
                        random_rest_probability: crawlerConfig['crawler-anti_ban_random_rest_probability']
                    }
                };
            } else if (crawlerName === 'weibo-follow') {
                if (!followConfig['follow-user_id_list'].trim()) {
                    ElementPlus.ElMessage.error('请输入用户ID');
                    return;
                }
                config = {
                    user_id_list: followConfig['follow-user_id_list'].split('\n').filter(id => id.trim()),
                    use_sqlite: followConfig['follow-use_sqlite'] || false,
                    use_mysql: followConfig['follow-use_mysql'] || false,
                    use_mongo: followConfig['follow-use_mongo'] || false
                };
            } else if (crawlerName === 'weibo-search') {
                if (!searchConfig['search-keyword'].trim()) {
                    ElementPlus.ElMessage.error('请输入关键词');
                    return;
                }
                // 校验日期范围
                if (!(await checkDateRange(
                    searchConfig['search-start_time'],
                    searchConfig['search-end_time']
                ))) return;
                // 发给后端的 params 使用原始键名
                config = {
                    keyword: searchConfig['search-keyword'],
                    start_time: searchConfig['search-start_time'],
                    end_time: searchConfig['search-end_time'],
                    search_type: searchConfig['search-search_type'],
                    filter_type: searchConfig['search-filter_type'],
                    sort_type: searchConfig['search-sort_type'],
                    region: searchConfig['search-region'],
                    further_threshold: searchConfig['search-further_threshold'],
                    limit_result: searchConfig['search-limit_result'],
                    max_pages: searchConfig['search-max_pages'],
                    wait_time: searchConfig['search-wait_time'],
                    images_store: searchConfig['search-images_store'],
                    files_store: searchConfig['search-files_store'],
                    use_csv: searchConfig['search-use_csv'],
                    use_mysql: searchConfig['search-use_mysql'],
                    use_mongo: searchConfig['search-use_mongo'],
                    use_sqlite: searchConfig['search-use_sqlite'],
                    use_images: searchConfig['search-use_images'],
                    use_videos: searchConfig['search-use_videos']
                };
            }
            
            // 启动前设置该爬虫为运行中
            runningCrawlers[crawlerName] = true;
            
            try {
                const response = await fetchWithRetry('/api/crawler/start', {
                    method: 'POST',
                    data: {
                        crawler_type: crawlerName,
                        params: config
                    }
                });
                if (response.data.success) {
                    ElementPlus.ElMessage.success('爬虫启动成功');
                    loadHistory();
                    // 启动轮询检查该爬虫状态
                    pollCrawlerStatus(crawlerName);
                } else {
                    ElementPlus.ElMessage.error(response.data.error || '启动失败');
                    runningCrawlers[crawlerName] = false;
                }
            } catch (error) {
                ElementPlus.ElMessage.error(error.response?.data?.error || '启动失败');
                runningCrawlers[crawlerName] = false;
            }
        };
        
        const stopCrawler = async (row) => {
            const crawlerType = row.crawler_name || row.crawler_type;
            confirmDialog.message = `确定要停止 ${crawlerType} 吗？`;
            confirmDialog.onConfirm = async () => {
                confirmDialog.visible = false;
                try {
                    await fetchWithRetry('/api/crawler/stop', {
                        method: 'POST',
                        data: { crawler_type: crawlerType }
                    });
                    ElementPlus.ElMessage.success('已发送停止信号');
                    // 更新该爬虫状态
                    runningCrawlers[crawlerType] = false;
                    setTimeout(loadHistory, 1000);
                } catch (error) {
                    ElementPlus.ElMessage.error('停止失败: ' + (error.response?.data?.error || error.message));
                }
            };
            confirmDialog.visible = true;
        };
        
        const reuseParams = (row) => {
            const crawlerName = row.crawler_name || row.crawler_type;
            navigateTo(crawlerName);
            setTimeout(() => {
                loadLastParams(crawlerName, row.id);
            }, 100);
        };
        
        const deleteHistory = async (row) => {
            confirmDialog.message = `确定要删除这条历史记录吗？${row.config_file ? `\n关联配置文件 ${row.config_file} 也会一并删除。` : ''}`;
            confirmDialog.onConfirm = async () => {
                confirmDialog.visible = false;
                try {
                    await axios.delete(`/api/history/${encodeURIComponent(row.id)}`);
                    ElementPlus.ElMessage.success('删除成功');
                    loadHistory();
                } catch (error) {
                    ElementPlus.ElMessage.error(error.response?.data?.error || '删除失败');
                }
            };
            confirmDialog.visible = true;
        };
        
        const clearAllHistory = async () => {
            confirmDialog.message = '确定要清空所有历史记录吗？此操作不可恢复，关联配置文件也会一并删除。';
            confirmDialog.onConfirm = async () => {
                confirmDialog.visible = false;
                try {
                    await axios.delete('/api/history');
                    ElementPlus.ElMessage.success('清空成功');
                    loadHistory();
                } catch (error) {
                    ElementPlus.ElMessage.error(error.response?.data?.error || '清空失败');
                }
            };
            confirmDialog.visible = true;
        };
        
        const loadLastParams = async (crawlerName, historyId = null) => {
            let params = null;
            try {
                if (historyId) {
                    const response = await axios.get(`/api/history/${encodeURIComponent(historyId)}/params`);
                    params = response.data?.params || null;
                } else {
                    const response = await axios.get(`/api/last-params/${crawlerName}`);
                    params = response.data || null;
                }
            } catch (error) {
                if (error.response?.status === 404) {
                    ElementPlus.ElMessage.info('没有找到可加载的历史配置');
                } else {
                    ElementPlus.ElMessage.error(error.response?.data?.error || '加载参数失败');
                }
                return;
            }
            
            if (!params || Object.keys(params).length === 0) {
                ElementPlus.ElMessage.info('没有找到运行参数');
                return;
            }
            
            try {
                if (crawlerName === 'weibo-crawler') {
                    // 解析 write_mode 数组
                    const wm = Array.isArray(params.write_mode) ? params.write_mode : [];
                    // 解析 anti_ban_config
                    const ab = params.anti_ban_config || {};
                    // 解析 post_config
                    const pc = params.post_config || {};
                    // 解析 query_list
                    let queryList = '';
                    if (Array.isArray(params.query_list)) {
                        queryList = params.query_list.join(',');
                    } else if (typeof params.query_list === 'string') {
                        queryList = params.query_list;
                    }
                    Object.assign(crawlerConfig, {
                        'crawler-user_id_list': Array.isArray(params.user_id_list) ? params.user_id_list.join('\n') : (params.user_id_list || ''),
                        'crawler-only_crawl_original': params.only_crawl_original !== 0 && params.only_crawl_original !== false,
                        'crawler-query_list': queryList,
                        'crawler-since_date': params.since_date !== undefined ? String(params.since_date) : '',
                        'crawler-end_date': params.end_date || '',
                        'crawler-start_page': params.start_page || 1,
                        'crawler-page_weibo_count': params.page_weibo_count || 20,
                        'crawler-write_mode_csv': wm.includes('csv'),
                        'crawler-write_mode_json': wm.includes('json'),
                        'crawler-write_mode_markdown': wm.includes('markdown'),
                        'crawler-write_mode_sqlite': wm.includes('sqlite'),
                        'crawler-write_mode_mysql': wm.includes('mysql'),
                        'crawler-write_mode_mongo': wm.includes('mongo'),
                        'crawler-write_mode_post': wm.includes('post'),
                        'crawler-markdown_split_by': params.markdown_split_by || 'day_by_month',
                        'crawler-output_directory': (!params.output_directory || ['weibo_data', 'weibo', '.', './'].includes(String(params.output_directory).trim())) ? '/app/data/weibo-crawler' : params.output_directory,
                        'crawler-user_id_as_folder_name': params.user_id_as_folder_name === 1 || params.user_id_as_folder_name === true,
                        'crawler-remove_html_tag': params.remove_html_tag !== 0 && params.remove_html_tag !== false,
                        'crawler-original_pic_download': params.original_pic_download === 1 || params.original_pic_download === true,
                        'crawler-retweet_pic_download': params.retweet_pic_download === 1 || params.retweet_pic_download === true,
                        'crawler-original_video_download': params.original_video_download === 1 || params.original_video_download === true,
                        'crawler-retweet_video_download': params.retweet_video_download === 1 || params.retweet_video_download === true,
                        'crawler-original_live_photo_download': params.original_live_photo_download === 1 || params.original_live_photo_download === true,
                        'crawler-retweet_live_photo_download': params.retweet_live_photo_download === 1 || params.retweet_live_photo_download === true,
                        'crawler-avatar_download': params.avatar_download === 1 || params.avatar_download === true,
                        'crawler-write_time_in_exif': params.write_time_in_exif !== 0 && params.write_time_in_exif !== false,
                        'crawler-change_file_time': params.change_file_time !== 0 && params.change_file_time !== false,
                        'crawler-download_comment': params.download_comment === 1 || params.download_comment === true,
                        'crawler-comment_max_download_count': params.comment_max_download_count || 100,
                        'crawler-comment_pic_download': params.comment_pic_download === 1 || params.comment_pic_download === true,
                        'crawler-download_repost': params.download_repost === 1 || params.download_repost === true,
                        'crawler-repost_max_download_count': params.repost_max_download_count || 100,
                        'crawler-store_binary_in_sqlite': params.store_binary_in_sqlite === 1 || params.store_binary_in_sqlite === true,
                        'crawler-post_config_url': pc.api_url || '',
                        'crawler-post_config_token': pc.api_token || '',
                        'crawler-anti_ban_enabled': ab.enabled !== false,
                        'crawler-anti_ban_max_weibo_per_session': ab.max_weibo_per_session || 500,
                        'crawler-anti_ban_batch_size': ab.batch_size || 50,
                        'crawler-anti_ban_batch_delay': ab.batch_delay || 30,
                        'crawler-anti_ban_request_delay_min': ab.request_delay_min || 8,
                        'crawler-anti_ban_request_delay_max': ab.request_delay_max || 15,
                        'crawler-anti_ban_max_session_time': ab.max_session_time || 600,
                        'crawler-anti_ban_max_api_errors': ab.max_api_errors || 5,
                        'crawler-anti_ban_rest_time_min': ab.rest_time_min || 180,
                        'crawler-anti_ban_random_rest_probability': ab.random_rest_probability !== undefined ? ab.random_rest_probability : 0.01
                    });
                } else if (crawlerName === 'weibo-follow') {
                    Object.assign(followConfig, {
                        'follow-user_id_list': Array.isArray(params.user_id_list) ? params.user_id_list.join('\n') : (params.user_id_list || ''),
                        'follow-use_sqlite': params.use_sqlite || false,
                        'follow-use_mysql': params.use_mysql || false,
                        'follow-use_mongo': params.use_mongo || false
                    });
                } else if (crawlerName === 'weibo-search') {
                    // 兼容前端键名 (keyword/start_time/end_time) 和后端键名 (KEYWORD_LIST/START_DATE/END_DATE)
                    let keyword = params.keyword || params.KEYWORD_LIST || '';
                    if (Array.isArray(keyword)) {
                        keyword = keyword[0] || '';
                    } else if (typeof keyword === 'string' && keyword.includes('[')) {
                        keyword = keyword.split('[')[0].replace(/['"]/g, '');
                    }
                    // 处理地区（多个用逗号分隔）
                    let region = params.region || params.REGION || '全部';
                    if (Array.isArray(region)) {
                        region = region.join(', ');
                    }
                    Object.assign(searchConfig, {
                        'search-keyword': keyword,
                        'search-start_time': params.start_time || params.START_DATE || '',
                        'search-end_time': params.end_time || params.END_DATE || '',
                        'search-search_type': String(params.search_type || params.WEIBO_TYPE || '1'),
                        'search-filter_type': String(params.filter_type || params.CONTAIN_TYPE || '0'),
                        'search-sort_type': String(params.sort_type || '1'),
                        'search-region': region,
                        'search-further_threshold': params.further_threshold || params.FURTHER_THRESHOLD || 46,
                        'search-limit_result': params.limit_result || params.LIMIT_RESULT || 0,
                        'search-max_pages': params.max_pages || params.MAX_PAGES || 100,
                        'search-wait_time': params.wait_time || params.DOWNLOAD_DELAY || 5,
                        'search-images_store': (!String(params.images_store || params.IMAGES_STORE || '').trim() || ['.', './', '结果文件'].includes(String(params.images_store || params.IMAGES_STORE || '').trim())) ? '/app/data/weibo-search/images' : (params.images_store || params.IMAGES_STORE),
                        'search-files_store': (!String(params.files_store || params.FILES_STORE || '').trim() || ['.', './', '结果文件'].includes(String(params.files_store || params.FILES_STORE || '').trim())) ? '/app/data/weibo-search/files' : (params.files_store || params.FILES_STORE),
                        'search-use_csv': params.use_csv !== false,
                        'search-use_mysql': params.use_mysql === true,
                        'search-use_mongo': params.use_mongo === true,
                        'search-use_sqlite': params.use_sqlite === true,
                        'search-use_images': params.use_images === true,
                        'search-use_videos': params.use_videos === true
                    });
                }
                ElementPlus.ElMessage.success('已加载上次参数');
            } catch (error) {
                ElementPlus.ElMessage.error('加载参数失败');
            }
        };
        
        const getLogFilename = (target) => target?.filename || target?.log_filename || '';

        const viewLog = async (target) => {
            const filename = getLogFilename(target);
            if (!filename) {
                ElementPlus.ElMessage.warning('该记录还没有可查看的日志文件');
                return;
            }

            try {
                const response = await axios.get(`/api/logs/file/${encodeURIComponent(filename)}`);
                logDialog.content = response.data.content || '';
                logDialog.visible = true;
            } catch (error) {
                ElementPlus.ElMessage.error('读取日志失败');
            }
        };

        const viewHistoryLog = (row) => viewLog({ log_filename: row.log_filename });
        
        const deleteLog = async (file) => {
            const filename = getLogFilename(file);
            confirmDialog.message = `确定要删除日志文件 ${filename} 吗？`;
            confirmDialog.onConfirm = async () => {
                confirmDialog.visible = false;
                try {
                    await axios.delete(`/api/logs/${encodeURIComponent(filename)}`);
                    ElementPlus.ElMessage.success('删除成功');
                    loadLogFiles();
                } catch (error) {
                    ElementPlus.ElMessage.error('删除失败');
                }
            };
            confirmDialog.visible = true;
        };
        
        const clearAllLogs = async () => {
            confirmDialog.message = '确定要清空所有日志文件吗？此操作不可恢复。';
            confirmDialog.onConfirm = async () => {
                confirmDialog.visible = false;
                try {
                    await axios.delete('/api/logs');
                    ElementPlus.ElMessage.success('清空成功');
                    loadLogFiles();
                } catch (error) {
                    ElementPlus.ElMessage.error('清空失败');
                }
            };
            confirmDialog.visible = true;
        };
        
        const saveSettings = async () => {
            try {
                // Cookie 测试守卫：有 Cookie 但未验证时弹出确认
                if (settings.cookie && !settings.cookie_tested) {
                    try {
                        await ElementPlus.ElMessageBox.confirm(
                            'Cookie 已填写但未通过验证测试，确定要继续保存吗？\n未验证的 Cookie 可能导致爬虫登录失败、无法获取数据。',
                            '确认保存',
                            { confirmButtonText: '继续保存', cancelButtonText: '取消', type: 'warning' }
                        );
                    } catch {
                        return; // 用户取消
                    }
                }
                
                // 连接测试守卫：数据库启用但未测试通过时弹出确认
                const untestedDbs = [];
                if (settings.mysql_enabled && !settings.mysql_tested) {
                    untestedDbs.push('MySQL');
                }
                if (settings.mongo_enabled && !settings.mongo_tested) {
                    untestedDbs.push('MongoDB');
                }
                if (settings.sqlite_enabled && !settings.sqlite_tested) {
                    untestedDbs.push('SQLite');
                }
                if (untestedDbs.length > 0) {
                    const dbNames = untestedDbs.join('、');
                    try {
                        await ElementPlus.ElMessageBox.confirm(
                            `${dbNames} 已启用但未通过连接测试，确定要继续保存吗？\n未通过测试的数据库可能导致爬虫写入失败。`,
                            '确认保存',
                            { confirmButtonText: '继续保存', cancelButtonText: '取消', type: 'warning' }
                        );
                    } catch {
                        return; // 用户取消
                    }
                }

                await fetchWithRetry('/api/settings', {
                    method: 'POST',
                    data: {
                        cookie: settings.cookie,
                        timezone: settings.timezone,
                        mysql_config: {
                            enabled: settings.mysql_enabled,
                            default_enabled: settings.mysql_default,
                            host: settings.mysql_host,
                            port: settings.mysql_port,
                            user: settings.mysql_user,
                            password: settings.mysql_password,
                            database: settings.mysql_database,
                            charset: 'utf8mb4',
                        },
                        mongo_config: {
                            enabled: settings.mongo_enabled,
                            default_enabled: settings.mongo_default,
                            uri: settings.mongo_uri,
                        },
                        sqlite_config: {
                            enabled: settings.sqlite_enabled,
                            default_enabled: settings.sqlite_default,
                            db_path: settings.sqlite_db_path,
                        },
                        log_settings: {
                            level: settings.log_level,
                            max_keep: settings.log_keep_count,
                        },
                    }
                });
                ElementPlus.ElMessage.success('保存成功');
            } catch (error) {
                ElementPlus.ElMessage.error('保存失败: ' + (error.response?.data?.error || error.message));
            }
        };
        
        // 测试 Cookie
        const testCookie = async () => {
            if (!settings.cookie) {
                settings.cookie_tested = false;
                settings.cookie_test_status = '';
                ElementPlus.ElMessage.warning('请先输入 Cookie');
                return;
            }
            testing.cookie = true;
            try {
                const response = await axios.post('/api/cookie/verify', { cookie: settings.cookie });
                if (response.data.valid) {
                    settings.cookie_tested = true;
                    settings.cookie_test_status = 'success';
                    ElementPlus.ElMessage.success('Cookie 有效');
                } else {
                    settings.cookie_tested = false;
                    settings.cookie_test_status = 'fail';
                    ElementPlus.ElMessage.error('Cookie 无效: ' + (response.data.message || '未知错误'));
                }
            } catch (error) {
                settings.cookie_tested = false;
                settings.cookie_test_status = 'fail';
                ElementPlus.ElMessage.error('Cookie 验证失败: ' + (error.response?.data?.message || error.message));
            } finally {
                testing.cookie = false;
            }
        };
        
        // 测试 MySQL 连接
        const testMysql = async () => {
            if (!settings.mysql_host || !settings.mysql_user) {
                ElementPlus.ElMessage.warning('请填写 MySQL 连接信息');
                return;
            }
            testing.mysql = true;
            settings.mysql_tested = false;
            settings.mysql_test_status = '';
            try {
                const response = await axios.post('/api/mysql/test', {
                    mysql_config: {
                        host: settings.mysql_host,
                        port: settings.mysql_port,
                        user: settings.mysql_user,
                        password: settings.mysql_password,
                        database: settings.mysql_database,
                        charset: 'utf8mb4'
                    }
                });
                if (response.data.success) {
                    settings.mysql_tested = true;
                    settings.mysql_test_status = 'success';
                    ElementPlus.ElMessage.success('MySQL 连接成功');
                } else {
                    settings.mysql_tested = false;
                    settings.mysql_test_status = 'fail';
                    ElementPlus.ElMessage.error('MySQL 连接失败: ' + (response.data.error || '未知错误'));
                }
            } catch (error) {
                settings.mysql_tested = false;
                settings.mysql_test_status = 'fail';
                ElementPlus.ElMessage.error('MySQL 连接失败: ' + (error.response?.data?.error || error.message));
            } finally {
                testing.mysql = false;
            }
        };

        // 测试 MongoDB 连接
        const testMongo = async () => {
            if (!settings.mongo_uri) {
                ElementPlus.ElMessage.warning('请填写 MongoDB URI');
                return;
            }
            testing.mongo = true;
            settings.mongo_tested = false;
            settings.mongo_test_status = '';
            try {
                const response = await axios.post('/api/mongo/test', {
                    mongo_uri: settings.mongo_uri
                });
                if (response.data.success) {
                    settings.mongo_tested = true;
                    settings.mongo_test_status = 'success';
                    ElementPlus.ElMessage.success('MongoDB 连接成功');
                } else {
                    settings.mongo_tested = false;
                    settings.mongo_test_status = 'fail';
                    ElementPlus.ElMessage.error('MongoDB 连接失败: ' + (response.data.error || '未知错误'));
                }
            } catch (error) {
                settings.mongo_tested = false;
                settings.mongo_test_status = 'fail';
                ElementPlus.ElMessage.error('MongoDB 连接失败: ' + (error.response?.data?.error || error.message));
            } finally {
                testing.mongo = false;
            }
        };

        // 测试 SQLite 路径
        const testSqlite = async () => {
            if (!settings.sqlite_db_path) {
                ElementPlus.ElMessage.warning('请填写 SQLite 数据库路径');
                return;
            }
            testing.sqlite = true;
            settings.sqlite_tested = false;
            settings.sqlite_test_status = '';
            try {
                const response = await axios.post('/api/sqlite/test', {
                    db_path: settings.sqlite_db_path
                });
                if (response.data.success) {
                    settings.sqlite_tested = true;
                    settings.sqlite_test_status = 'success';
                    ElementPlus.ElMessage.success('SQLite 路径可用');
                } else {
                    settings.sqlite_tested = false;
                    settings.sqlite_test_status = 'fail';
                    ElementPlus.ElMessage.error('SQLite 路径不可用: ' + (response.data.error || '未知错误'));
                }
            } catch (error) {
                settings.sqlite_tested = false;
                settings.sqlite_test_status = 'fail';
                ElementPlus.ElMessage.error('SQLite 路径测试失败: ' + (error.response?.data?.error || error.message));
            } finally {
                testing.sqlite = false;
            }
        };
        
        const pollCrawlerStatus = async (crawlerName) => {
            // 轮询检查特定爬虫的状态
            const check = async () => {
                try {
                    const response = await axios.get('/api/status');
                    const runningCrawlersData = response.data.running_crawlers || {};
                    
                    if (crawlerName in runningCrawlersData) {
                        // 该爬虫仍在运行，继续轮询
                        setTimeout(check, 3000);
                    } else {
                        // 爬虫已停止
                        runningCrawlers[crawlerName] = false;
                        await loadHistory();
                        const latestRecord = getLatestHistoryRecord(crawlerName);
                        if (!latestRecord) {
                            ElementPlus.ElMessage.info('爬虫已结束');
                        } else if (latestRecord.status === 'success') {
                            ElementPlus.ElMessage.success('爬虫已运行完成');
                        } else if (latestRecord.status === 'failed') {
                            ElementPlus.ElMessage.error(latestRecord.failure_reason || latestRecord.summary || '爬虫运行失败');
                        } else if (latestRecord.status === 'stopped') {
                            ElementPlus.ElMessage.warning('爬虫已手动停止');
                        } else {
                            ElementPlus.ElMessage.info('爬虫已结束');
                        }
                    }
                } catch (error) {
                    console.error('检查状态失败', error);
                }
            };
            check();
        };

        const checkRunningStatus = async () => {
            try {
                const response = await axios.get('/api/status');
                const runningCrawlersData = response.data.running_crawlers || {};
                
                // 更新所有爬虫的状态：检查每种类型是否在运行中
                for (const key of Object.keys(runningCrawlers)) {
                    runningCrawlers[key] = (key in runningCrawlersData);
                }
                
                // 只要有任意爬虫在运行，就继续轮询
                if (Object.keys(runningCrawlersData).length > 0) {
                    setTimeout(checkRunningStatus, 3000);
                }
            } catch (error) {
                console.error('检查状态失败', error);
            }
        };
        
        // 监听菜单切换：根据全局设置自动勾选/取消勾选数据库复选框
        // 首次进入页面时应用全局默认设置
        let defaultCheckApplied = { crawler: false, follow: false, search: false };

        const applyDefaultDbChecks = (page) => {
            if (page === 'weibo-crawler' && !defaultCheckApplied.crawler) {
                defaultCheckApplied.crawler = true;
                crawlerConfig['crawler-write_mode_sqlite'] = settings.sqlite_default;
                crawlerConfig['crawler-write_mode_mysql'] = settings.mysql_default;
                crawlerConfig['crawler-write_mode_mongo'] = settings.mongo_default;
            } else if (page === 'weibo-follow' && !defaultCheckApplied.follow) {
                defaultCheckApplied.follow = true;
                followConfig['follow-use_sqlite'] = settings.sqlite_default;
                followConfig['follow-use_mysql'] = settings.mysql_default;
                followConfig['follow-use_mongo'] = settings.mongo_default;
            } else if (page === 'weibo-search' && !defaultCheckApplied.search) {
                defaultCheckApplied.search = true;
                searchConfig['search-use_sqlite'] = settings.sqlite_default;
                searchConfig['search-use_mysql'] = settings.mysql_default;
                searchConfig['search-use_mongo'] = settings.mongo_default;
            }
        };

        watch(activeMenu, (newVal) => {
            if (['weibo-crawler', 'weibo-follow', 'weibo-search'].includes(newVal)) {
                applyDefaultDbChecks(newVal);
            }
        });

        // 只爬原创微博时，自动取消勾选并禁用转发微博下载选项
        watch(() => crawlerConfig['crawler-only_crawl_original'], (onlyOriginal) => {
            if (onlyOriginal) {
                crawlerConfig['crawler-retweet_pic_download'] = false;
                crawlerConfig['crawler-retweet_video_download'] = false;
                crawlerConfig['crawler-retweet_live_photo_download'] = false;
            }
        });

        // SQLite 输出取消时，自动取消勾选并禁用依赖 SQLite 的选项
        watch(() => crawlerConfig['crawler-write_mode_sqlite'], (sqliteEnabled) => {
            if (!sqliteEnabled) {
                crawlerConfig['crawler-store_binary_in_sqlite'] = false;
                crawlerConfig['crawler-download_comment'] = false;
                crawlerConfig['crawler-comment_pic_download'] = false;
                crawlerConfig['crawler-download_repost'] = false;
            }
        });

        // 下载评论取消时，自动取消勾选并禁用子选项
        watch(() => crawlerConfig['crawler-download_comment'], (commentEnabled) => {
            if (!commentEnabled) {
                crawlerConfig['crawler-comment_pic_download'] = false;
            }
        });

        // 生命周期
        onMounted(() => {
            // 从 localStorage 恢复表单配置
            const restoreConfig = (key, target) => {
                const saved = storage.get(key);
                if (saved && typeof saved === 'object') {
                    for (const [k, v] of Object.entries(saved)) {
                        if (k in target && typeof v !== 'function') target[k] = v;
                    }
                }
            };
            restoreConfig('crawlerConfig', crawlerConfig);
            restoreConfig('followConfig', followConfig);
            restoreConfig('searchConfig', searchConfig);

            loadHistory();
            checkRunningStatus();
            
            // 从 localStorage 恢复筛选和分页设置 (带数据校验)
            const savedFilter = localStorage.getItem('historyFilter');
            if (savedFilter) {
                try {
                    const parsed = JSON.parse(savedFilter);
                    // 确保是普通对象且值为字符串
                    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                        if (typeof parsed.type === 'string') historyFilter.type = parsed.type;
                        if (typeof parsed.status === 'string') historyFilter.status = parsed.status;
                    }
                } catch (e) {
                    console.warn('恢复 historyFilter 失败:', e);
                }
            }
            const savedPagination = localStorage.getItem('pagination');
            if (savedPagination) {
                try {
                    const parsed = JSON.parse(savedPagination);
                    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                        Object.assign(pagination, parsed);
                    }
                } catch (e) {
                    console.warn('恢复 pagination 失败:', e);
                }
            }
        });
        
        // 监听筛选和分页变化，保存到 localStorage
        watch(historyFilter, (newVal) => {
            localStorage.setItem('historyFilter', JSON.stringify(newVal));
        }, { deep: true });
        
        watch(pagination, (newVal) => {
            localStorage.setItem('pagination', JSON.stringify(newVal));
        }, { deep: true });

        // 自动持久化爬虫配置（避免页面刷新丢失）
        autoPersist('crawlerConfig', crawlerConfig);
        autoPersist('followConfig', followConfig);
        autoPersist('searchConfig', searchConfig);
        
        return {
            activeMenu,
            loading,
            runningCrawlers,
            history,
            logFiles,
            historyFilter,
            pagination,
            crawlerConfig,
            followConfig,
            searchConfig,
            settings,
            logDialog,
            confirmDialog,
            featureCards,
            filteredHistory,
            paginatedHistory,
            handleMenuSelect,
            navigateTo,
            formatTime,
            getCrawlerType,
            getCrawlerShortName,
            getHistorySummary,
            getHistoryExtraInfo,
            hasHistoryExtraInfo,
            getStatusType,
            getStatusText,
            handleSortChange,
            startCrawler,
            stopCrawler,
            reuseParams,
            deleteHistory,
            clearAllHistory,
            loadLastParams,
            viewLog,
            viewHistoryLog,
            deleteLog,
            clearAllLogs,
            saveSettings,
            testCookie,
            testMysql,
            testMongo,
            testSqlite,
            testing
        };
    }
});

// 注册 Element Plus 图标 (兼容不同 CDN 来源的变量名)
const IconsVue = window.ElementPlusIconsVue || window.ElementPlusIcons || window.ElIcons;
if (IconsVue) {
    for (const [key, component] of Object.entries(IconsVue)) {
        app.component(key, component);
    }
}

app.use(ElementPlus, {
    locale: window.ElementPlusLocaleZhCn || undefined
});
app.mount('#app');
