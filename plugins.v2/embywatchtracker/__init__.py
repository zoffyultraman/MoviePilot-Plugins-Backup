"""
Emby Watch Tracker Plugin for MoviePilot V2

Syncs Emby user watch history and provides watch tracking features.
"""
from typing import Optional, List, Dict, Any, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaServerType
from app.helper.mediaserver import MediaServerHelper
from app.core.config import settings
from app.log import logger

from .emby_client import EmbyClient
from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord, EpisodeWatchRecord
from .matcher import MediaMatcher
from .notifier import WatchTrackerNotifier
from .ui import WatchTrackerUI


class EmbyWatchTrackerPlugin(_PluginBase):
    """Emby Watch Tracker Plugin for MoviePilot V2"""

    # 插件名称
    plugin_name = "Emby观影追踪"
    # 插件描述
    plugin_desc = "同步Emby用户观影记录，在MoviePilot中展示已观看媒体"
    # 插件图标
    plugin_icon = "emby.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "zoffyultraman"
    # 作者主页
    author_url = "https://github.com/zoffyultraman"
    # 插件配置项ID前缀
    plugin_config_prefix = "embywatchtracker_"
    # 加载顺序
    plugin_order = 9999
    # 可使用的用户级别，1为所有用户可见，2为仅认证用户可见
    auth_level = 1

    # Storage keys
    STORAGE_KEY_HISTORY = "watch_history"

    def __init__(self):
        super().__init__()
        self._emby_client: Optional[EmbyClient] = None
        self._user_id: Optional[str] = None
        self._username: Optional[str] = None
        self._matcher: Optional[MediaMatcher] = None
        self._notifier: Optional[WatchTrackerNotifier] = None
        self._scheduler = None
        # Config values
        self._selected_server: str = ""
        self._server_url: str = ""
        self._api_key: str = ""
        self._emby_username: str = ""
        self._sync_interval_hours: int = 6
        self._enable_notification: bool = True
        self._fuzzy_threshold: float = 0.9
        self._incremental_sync: bool = True
        self._onlyonce: bool = False

    def _get_emby_servers(self) -> List[Dict[str, str]]:
        """
        Get list of configured Emby servers from MoviePilot

        :return: List of server info dicts with name, url, api_key
        """
        servers = []
        try:
            # Use MediaServerHelper to get all media server configs
            all_configs = MediaServerHelper().get_configs(include_disabled=True)
            for name, config in all_configs.items():
                if config.type == MediaServerType.Emby.value:
                    server_config = config.config or {}
                    servers.append({
                        "name": name,
                        "url": server_config.get("url", ""),
                        "api_key": server_config.get("api_key", "")
                    })
        except Exception as e:
            logger.error(f"Failed to get Emby servers: {e}")
        return servers

    def init_plugin(self, config: dict = None) -> None:
        """
        Initialize plugin with configuration

        :param config: Plugin configuration
        """
        logger.info("Initializing Emby Watch Tracker Plugin")

        if not config:
            config = self.get_config() or {}
        logger.info(f"init_plugin received config: {config}")

        # Load configuration
        self._selected_server = config.get("emby_server", "")
        self._emby_username = config.get("emby_username", "")
        self._sync_interval_hours = int(config.get("sync_interval_hours", 6))
        self._enable_notification = config.get("enable_notification", True)
        self._fuzzy_threshold = float(config.get("fuzzy_match_threshold", 0.9))
        self._incremental_sync = config.get("enable_incremental_sync", True)
        self._onlyonce = config.get("onlyonce", False)

        # Auto-get server config from MoviePilot
        if not self._selected_server:
            logger.warning("Emby Watch Tracker plugin is not configured: no server selected")
            return

        if not self._use_moviepilot_server(self._selected_server):
            logger.warning("Emby Watch Tracker plugin is not fully configured")
            return

        if not self._emby_username:
            logger.warning("Emby Watch Tracker plugin is not configured: no username")
            return

        # Initialize Emby client
        logger.info(f"Creating EmbyClient with server: {self._server_url}")
        self._emby_client = EmbyClient(
            server_url=self._server_url,
            api_key=self._api_key
        )
        logger.info(f"EmbyClient created, testing connection...")
        if not self._emby_client.test_connection():
            logger.error("Emby server connection test failed")
            return
        logger.info("Emby server connection test passed")

        # Authenticate user
        logger.info(f"Looking for user: {self._emby_username}")
        user = self._emby_client.get_user_by_name(self._emby_username)
        if not user:
            logger.error(f"Failed to find Emby user: {self._emby_username}")
            return
        logger.info(f"Found user: name={user.username}, id={user.user_id}")

        # Handle immediate sync if onlyonce is enabled
        if self._onlyonce:
            logger.info("Running immediate sync...")
            self._do_sync()
            self._onlyonce = False
            # Reset onlyonce in config without overwriting other settings
            current_config = self.get_config() or {}
            current_config["onlyonce"] = False
            self.update_config(config=current_config)

        self._user_id = user.user_id
        self._username = user.username
        logger.info(f"Authenticated as Emby user: {user.username}")

        # Initialize matcher and notifier
        history = self._load_history()
        self._matcher = MediaMatcher(history, self._fuzzy_threshold)
        self._notifier = WatchTrackerNotifier(self._matcher, self._enable_notification)

        # Register events
        self._register_events()

        logger.info("Emby Watch Tracker Plugin initialized successfully")

    def _use_moviepilot_server(self, server_name: str) -> bool:
        """
        Use Emby server configured in MoviePilot

        :param server_name: Server name in MoviePilot
        :return: True if successful
        """
        try:
            # Use MediaServerHelper to get server config
            logger.info(f"Looking up server config for: {server_name}")
            config = MediaServerHelper().get_config(server_name)
            logger.info(f"Config result: {config}")
            if not config:
                logger.warning(f"Server {server_name} not found in MediaServerHelper")
                return False
            if config.type and config.type.lower() != "emby":
                logger.warning(f"Server {server_name} is not an Emby server, type is: {config.type}")
                return False

            server_config = config.config or {}
            logger.info(f"Server config: {server_config}")
            # Handle both possible key names (MoviePilot uses host/apikey, not url/api_key)
            self._server_url = server_config.get("url") or server_config.get("host", "").rstrip("/")
            self._api_key = server_config.get("api_key") or server_config.get("apikey", "")
            logger.info(f"Set server_url: {self._server_url}, api_key: {self._api_key[:4] if self._api_key else 'None'}...")
            return True
        except Exception as e:
            logger.error(f"Failed to use MoviePilot server: {e}")
            return False

    def get_state(self) -> bool:
        """
        Get plugin running state

        :return: True if plugin is loaded
        """
        return True

    def stop_service(self) -> None:
        """Stop plugin service"""
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            self._scheduler = None
        logger.info("Emby Watch Tracker Plugin stopped")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Get plugin configuration form

        :return: (form config, default values)
        """
        # Load config from persistent storage
        config = self.get_config() or {}
        logger.info(f"get_form config: {config}")
        selected_server = config.get("emby_server", "")
        emby_username = config.get("emby_username", "")
        sync_interval_hours = int(config.get("sync_interval_hours", 6))
        enable_notification = config.get("enable_notification", True)
        fuzzy_threshold = float(config.get("fuzzy_match_threshold", 0.9))
        enable_incremental_sync = config.get("enable_incremental_sync", True)
        logger.info(f"get_form selected_server: {selected_server}, emby_username: {emby_username}")

        # Build server items from MoviePilot media server configs
        all_configs = MediaServerHelper().get_configs(include_disabled=True)
        logger.info(f"All media server configs: {[c.name for c in all_configs.values()]}")
        logger.info(f"All config types: {[c.type for c in all_configs.values()]}")
        # Emby type check - need case insensitive comparison
        server_items = [
            {"title": config.name, "value": config.name}
            for config in all_configs.values()
            if config.type and config.type.lower() == "emby"
        ]
        logger.info(f"Emby server items: {server_items}")

        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "label": "选择Emby服务器",
                                            "placeholder": "请选择MoviePilot中配置的Emby服务器",
                                            "model": "emby_server",
                                            "items": server_items,
                                            "clearable": False,
                                            "hint": "自动读取MoviePilot中已配置的Emby服务器"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "label": "Emby用户名",
                                            "placeholder": "输入要追踪的Emby用户名",
                                            "model": "emby_username",
                                            "clearable": True,
                                            "hint": "输入你在Emby中登录的用户名"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "label": "同步间隔（小时）",
                                            "model": "sync_interval_hours",
                                            "items": [
                                                {"title": "1小时", "value": 1},
                                                {"title": "3小时", "value": 3},
                                                {"title": "6小时", "value": 6},
                                                {"title": "12小时", "value": 12},
                                                {"title": "24小时", "value": 24}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "label": "启用增量同步",
                                            "model": "enable_incremental_sync",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "label": "立即同步一次",
                                            "model": "onlyonce",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "label": "启用订阅提醒",
                                            "model": "enable_notification",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSlider",
                                        "props": {
                                            "label": "模糊匹配阈值",
                                            "model": "fuzzy_match_threshold",
                                            "min": 0.7,
                                            "max": 1.0,
                                            "step": 0.05,
                                            "thumbLabel": True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "error",
                                            "variant": "outlined",
                                        },
                                        "text": "清空历史记录",
                                        "events": {
                                            "click": {
                                                "api": "plugin/EmbyWatchTracker/clear_history",
                                                "method": "get",
                                                "params": {"token": settings.API_TOKEN},
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        defaults = {
            "emby_server": selected_server,
            "emby_username": emby_username,
            "sync_interval_hours": sync_interval_hours,
            "enable_notification": enable_notification,
            "fuzzy_match_threshold": fuzzy_threshold,
            "enable_incremental_sync": enable_incremental_sync,
            "onlyonce": False
        }

        return form, defaults

    def get_api(self) -> List[Dict[str, Any]]:
        """
        Get plugin API endpoints

        :return: API definitions
        """
        logger.info("get_api called, registering clear_history endpoint")
        return [
            {
                "path": "/clear_history",
                "endpoint": self._clear_history,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "清空观影历史记录",
            }
        ]

    def _clear_history(self, token: str = "") -> dict:
        """清空观影历史记录"""
        logger.info(f"_clear_history called with token length: {len(token) if token else 0}")
        from app.core.config import settings
        if token != settings.API_TOKEN:
            logger.warning("Token mismatch")
            return {"success": False, "message": "认证失败"}
        logger.info("Clearing history...")
        self.save_data(self.STORAGE_KEY_HISTORY, {"movies": [], "tv_shows": [], "last_sync_time": 0})
        logger.info("观影历史已清空")
        return {"success": True, "message": "历史已清空"}

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面
        """
        logger.info("get_page called")
        try:
            history = self._load_history()
            logger.info(f"history loaded: {len(history.movies)} movies, {len(history.tv_shows)} tvshows")
        except Exception as e:
            logger.error(f"_load_history error: {e}")
            history = None

        # 计算统计数据
        movie_count = len(history.movies) if history else 0
        tvshow_count = len(history.tv_shows) if history else 0
        episode_count = sum(len(tv.episodes) for tv in history.tv_shows) if history else 0

        # 电影表格
        movie_rows = []
        if history:
            for movie in history.movies:
                movie_rows.append({
                    'component': 'tr',
                    'content': [
                        {'component': 'td', 'text': movie.name}
                    ]
                })

        # 电视剧表格 - 格式化为 S01: 1-3,5-8 | S02: 9-13 形式
        def format_season_episodes(episodes):
            """将剧集合并为季别格式，处理不连续的集数"""
            from collections import defaultdict
            # 按季分组
            seasons = defaultdict(list)
            for ep in episodes:
                if ep.season is not None:
                    seasons[ep.season].append(ep.episode)

            # 生成格式字符串
            parts = []
            for season in sorted(seasons.keys()):
                eps = sorted(set(seasons[season]))
                if len(eps) == 1:
                    parts.append(f"S{season:02d}: {eps[0]}")
                else:
                    # 找出连续的范围
                    ranges = []
                    start = eps[0]
                    end = eps[0]
                    for i in range(1, len(eps)):
                        if eps[i] == end + 1:
                            end = eps[i]
                        else:
                            if start == end:
                                ranges.append(f"{start}")
                            else:
                                ranges.append(f"{start}-{end}")
                            start = eps[i]
                            end = eps[i]
                    # 处理最后一个范围
                    if start == end:
                        ranges.append(f"{start}")
                    else:
                        ranges.append(f"{start}-{end}")
                    parts.append(f"S{season:02d}: {','.join(ranges)}")
            return " | ".join(parts)

        tvshow_rows = []
        if history:
            for show in history.tv_shows:
                episode_format = format_season_episodes(show.episodes)
                tvshow_rows.append({
                    'component': 'tr',
                    'content': [
                        {'component': 'td', 'text': show.series_name},
                        {'component': 'td', 'text': episode_format}
                    ]
                })

        return [
            {
                'component': 'VTabs',
                'props': {
                    'model': '_tabs',
                    'style': {
                        'margin-top': '8px',
                        'margin-bottom': '16px'
                    },
                    'stacked': True,
                    'fixed-tabs': True
                },
                'content': [
                    {
                        'component': 'VTab',
                        'props': {'value': 'movies'},
                        'text': f"电影 ({movie_count})"
                    },
                    {
                        'component': 'VTab',
                        'props': {'value': 'tvshows'},
                        'text': f"电视剧 ({tvshow_count})"
                    }
                ]
            },
            {
                'component': 'VWindow',
                'props': {'model': '_tabs'},
                'content': [
                    {
                        'component': 'VWindowItem',
                        'props': {'value': 'movies'},
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {'hover': True, 'class': 'mt-4'},
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {'component': 'th', 'text': '电影名称'}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': movie_rows if movie_rows else [
                                            {'component': 'tr', 'content': [{'component': 'td', 'text': '暂无记录', 'props': {'colspan': 1}}]}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VWindowItem',
                        'props': {'value': 'tvshows'},
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {'hover': True, 'class': 'mt-4'},
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {'component': 'th', 'text': '剧集名称'},
                                                    {'component': 'th', 'text': '观看集数'}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': tvshow_rows if tvshow_rows else [
                                            {'component': 'tr', 'content': [{'component': 'td', 'text': '暂无记录', 'props': {'colspan': 2}}]}
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        Get plugin services for scheduling

        :return: Service definitions
        """
        return [
            {
                "id": "emby_watch_sync",
                "name": "Emby观影同步",
                "trigger": CronTrigger(hour=f"*/{self._sync_interval_hours or 6}"),
                "func": self._do_sync,
                "kwargs": {}
            }
        ]

    def _register_events(self):
        """Register event handlers"""
        self.eventmanager.register(EventType.SubscribeAdded)(self._on_subscribe_added)

    def _load_history(self) -> WatchHistory:
        """
        Load watch history from storage

        :return: WatchHistory object
        """
        data = self.get_data(self.STORAGE_KEY_HISTORY)
        if not data:
            return WatchHistory()

        try:
            history = WatchHistory()
            history.last_sync_time = data.get("last_sync_time", 0)

            for movie_data in data.get("movies", []):
                history.movies.append(MovieWatchRecord(**movie_data))

            for tv_data in data.get("tv_shows", []):
                episodes = [
                    EpisodeWatchRecord(**ep)
                    for ep in tv_data.get("episodes", [])
                ]
                history.tv_shows.append(TvShowWatchRecord(
                    series_name=tv_data.get("series_name", ""),
                    series_id=tv_data.get("series_id"),
                    episodes=episodes
                ))

            return history
        except Exception as e:
            logger.error(f"Failed to load watch history: {e}")
            return WatchHistory()

    def _save_history(self, history: WatchHistory) -> bool:
        """
        Save watch history to storage

        :param history: WatchHistory object
        :return: True if successful
        """
        try:
            data = {
                "movies": [
                    {"id": m.id, "name": m.name, "year": m.year, "watched_at": m.watched_at}
                    for m in history.movies
                ],
                "tv_shows": [
                    {
                        "series_name": tv.series_name,
                        "series_id": tv.series_id,
                        "episodes": [
                            {"id": ep.id, "season": ep.season, "episode": ep.episode,
                             "name": ep.name, "watched_at": ep.watched_at}
                            for ep in tv.episodes
                        ]
                    }
                    for tv in history.tv_shows
                ],
                "last_sync_time": history.last_sync_time
            }
            self.save_data(self.STORAGE_KEY_HISTORY, data)
            return True
        except Exception as e:
            logger.error(f"Failed to save watch history: {e}")
            return False

    def _do_sync(self) -> Tuple[int, int]:
        """
        Perform sync operation

        :return: Tuple of (movies_added, episodes_added)
        """
        if not self._emby_client or not self._user_id:
            logger.error("Emby client not initialized")
            return 0, 0

        logger.info("Starting Emby watch history sync")
        logger.info(f"User ID: {self._user_id}")

        try:
            history = self._load_history()
            logger.info("Fetching movies...")
            movies = self._emby_client.get_watched_movies(self._user_id)
            logger.info(f"Movies fetched: {movies}")

            logger.info("Fetching episodes...")
            episodes = self._emby_client.get_watched_episodes(self._user_id)
            logger.info(f"Episodes fetched: {episodes}")

            if movies is None:
                logger.error("Failed to fetch movies from Emby")
                return 0, 0

            if episodes is None:
                logger.error("Failed to fetch episodes from Emby")
                return 0, 0

            logger.info(f"Movies count: {len(movies)}, Episodes count: {len(episodes)}")

            movies_added = 0
            episodes_added = 0
            existing_movie_ids = {m.id for m in history.movies}

            for movie_item in movies:
                if movie_item.played and movie_item.id not in existing_movie_ids:
                    history.movies.append(MovieWatchRecord(
                        id=movie_item.id,
                        name=movie_item.name,
                        year=movie_item.year,
                        watched_at=movie_item.last_played_date
                    ))
                    movies_added += 1

            for episode_item in episodes:
                if episode_item.played:
                    episode_record = EpisodeWatchRecord(
                        id=episode_item.id,
                        season=episode_item.season_number or 0,
                        episode=episode_item.episode_number or 0,
                        name=episode_item.name,
                        watched_at=episode_item.last_played_date
                    )

                    series_name = episode_item.series_name or "Unknown Series"
                    found = False
                    for tv_show in history.tv_shows:
                        if tv_show.series_name == series_name:
                            for existing_ep in tv_show.episodes:
                                if (existing_ep.season == episode_record.season and
                                        existing_ep.episode == episode_record.episode):
                                    found = True
                                    break
                            if not found:
                                tv_show.episodes.append(episode_record)
                                episodes_added += 1
                            break

                    if not found:
                        history.tv_shows.append(TvShowWatchRecord(
                            series_name=series_name,
                            series_id=None,
                            episodes=[episode_record]
                        ))
                        episodes_added += 1

            history.last_sync_time = int(__import__("time").time())
            self._save_history(history)

            self._matcher = MediaMatcher(history, self._fuzzy_threshold)
            self._notifier = WatchTrackerNotifier(self._matcher, self._enable_notification)

            logger.info(f"Sync completed: {movies_added} movies, {episodes_added} episodes added")
            return movies_added, episodes_added

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return 0, 0

    def _on_subscribe_added(self, event) -> None:
        """
        Handle new subscription event

        :param event: SubscribeAdded event
        """
        if not self._notifier or not self._enable_notification:
            return

        event_data = event.event_data or {}
        subscribe_info = event_data.get("subscribe")

        if not subscribe_info:
            return

        title = subscribe_info.get("title")
        media_type = subscribe_info.get("type", "Movie")
        year = subscribe_info.get("year")

        if not title:
            return

        message = self._notifier.check_and_notify(title, media_type, year)

        if message:
            self.post_message(
                mtype=NotificationType.Plugin,
                title="Emby观影提醒",
                text=message
            )

