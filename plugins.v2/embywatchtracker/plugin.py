"""
Main plugin implementation for Emby Watch Tracker Plugin
"""
import logging
from typing import Optional, List, Dict, Any, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.core.event import EventManager

from .emby_client import EmbyClient
from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord, EpisodeWatchRecord
from .matcher import MediaMatcher
from .notifier import WatchTrackerNotifier
from .ui import WatchTrackerUI

logger = logging.getLogger(__name__)


class EmbyWatchTrackerPlugin(_PluginBase):
    """Emby Watch Tracker Plugin for MoviePilot V2"""

    # Plugin metadata
    plugin_name = "EmbyWatchTracker"
    plugin_version = "1.0.0"
    plugin_icon = "emby.png"
    plugin_desc = "同步Emby用户观影记录，在MoviePilot中展示已观看媒体"
    plugin_author = "MoviePilot Plugin Developer"
    plugin_order = 9999

    # Storage keys
    STORAGE_KEY_HISTORY = "watch_history"
    STORAGE_KEY_CONFIG = "emby_config"

    def __init__(self):
        super().__init__()
        self._emby_client: Optional[EmbyClient] = None
        self._user_id: Optional[str] = None
        self._username: Optional[str] = None
        self._matcher: Optional[MediaMatcher] = None
        self._notifier: Optional[WatchTrackerNotifier] = None
        self._scheduler = None
        # Config values
        self._server_url: str = ""
        self._api_key: str = ""
        self._emby_username: str = ""
        self._sync_interval_hours: int = 6
        self._enable_notification: bool = True
        self._fuzzy_threshold: float = 0.9
        self._incremental_sync: bool = True

    def init_plugin(self, config: dict = None) -> None:
        """
        Initialize plugin with configuration

        :param config: Plugin configuration
        """
        logger.info("Initializing Emby Watch Tracker Plugin")

        if not config:
            config = self.get_config() or {}

        # Load configuration
        self._server_url = config.get("emby_server_url", "").rstrip("/")
        self._api_key = config.get("emby_api_key", "")
        self._emby_username = config.get("emby_username", "")
        self._sync_interval_hours = int(config.get("sync_interval_hours", 6))
        self._enable_notification = config.get("enable_notification", True)
        self._fuzzy_threshold = float(config.get("fuzzy_match_threshold", 0.9))
        self._incremental_sync = config.get("enable_incremental_sync", True)

        if not self._server_url or not self._api_key or not self._emby_username:
            logger.warning("Emby Watch Tracker plugin is not fully configured")
            return

        # Initialize Emby client
        self._emby_client = EmbyClient(
            server_url=self._server_url,
            api_key=self._api_key
        )

        # Authenticate user
        user = self._emby_client.get_user_by_name(self._emby_username)
        if not user:
            logger.error(f"Failed to find Emby user: {self._emby_username}")
            return

        self._user_id = user.user_id
        self._username = user.username
        logger.info(f"Authenticated as Emby user: {user.username}")

        # Initialize matcher and notifier
        history = self._load_history()
        self._matcher = MediaMatcher(history, self._fuzzy_threshold)
        self._notifier = WatchTrackerNotifier(self._matcher, self._enable_notification)

        logger.info("Emby Watch Tracker Plugin initialized successfully")

    def get_state(self) -> bool:
        """
        Get plugin running state

        :return: True if plugin is configured and running
        """
        return self._emby_client is not None and self._user_id is not None

    def stop_service(self) -> None:
        """Stop plugin service"""
        # Cleanup will be handled by the scheduler
        logger.info("Emby Watch Tracker Plugin stopped")

    def get_api(self) -> List[Dict[str, Any]]:
        """
        Get plugin API endpoints

        :return: API definitions
        """
        return [
            {
                "path": "/embywatchtracker/sync",
                "endpoint": self.api_sync,
                "methods": ["GET"],
                "summary": "手动同步观影记录",
                "description": "立即触发Emby观影记录同步"
            },
            {
                "path": "/embywatchtracker/stats",
                "endpoint": self.api_stats,
                "methods": ["GET"],
                "summary": "获取观影统计",
                "description": "获取当前观影统计数据"
            },
            {
                "path": "/embywatchtracker/movies",
                "endpoint": self.api_movies,
                "methods": ["GET"],
                "summary": "获取电影列表",
                "description": "获取已观看电影列表"
            },
            {
                "path": "/embywatchtracker/tvshows",
                "endpoint": self.api_tvshows,
                "methods": ["GET"],
                "summary": "获取电视剧列表",
                "description": "获取已观看电视剧列表"
            },
            {
                "path": "/embywatchtracker/test",
                "endpoint": self.api_test_connection,
                "methods": ["GET"],
                "summary": "测试Emby连接",
                "description": "测试Emby服务器连接是否正常"
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """
        Get plugin configuration form

        :return: (form config, default values)
        """
        form = [
            {
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "Emby服务器配置"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VTextField",
                                "props": {
                                    "label": "Emby服务器地址",
                                    "placeholder": "http://localhost:8096",
                                    "model": "emby_server_url",
                                    "clearable": True
                                }
                            },
                            {
                                "component": "VTextField",
                                "props": {
                                    "label": "API Key",
                                    "placeholder": "Emby API Key",
                                    "model": "emby_api_key",
                                    "clearable": True,
                                    "type": "password"
                                }
                            },
                            {
                                "component": "VTextField",
                                "props": {
                                    "label": "用户名",
                                    "placeholder": "Emby登录用户名",
                                    "model": "emby_username",
                                    "clearable": True
                                }
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "同步设置"
                    },
                    {
                        "component": "VCardText",
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
                            },
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
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "提醒设置"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "label": "启用订阅提醒",
                                    "model": "enable_notification",
                                    "color": "primary"
                                }
                            },
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
            }
        ]

        defaults = {
            "emby_server_url": self._server_url,
            "emby_api_key": self._api_key,
            "emby_username": self._emby_username,
            "sync_interval_hours": self._sync_interval_hours,
            "enable_notification": self._enable_notification,
            "fuzzy_match_threshold": self._fuzzy_threshold,
            "enable_incremental_sync": self._incremental_sync
        }

        return form, defaults

    def get_page(self) -> Optional[List[dict]]:
        """
        Get plugin detail page

        :return: Page configuration with data
        """
        history = self._load_history()
        stats = WatchTrackerUI.build_stats(history)
        movies = WatchTrackerUI.build_movies_list(history)
        shows = WatchTrackerUI.build_tv_shows_list(history)

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 4},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "primary"},
                                "content": [
                                    {"component": "VCardText", "text": f"电影: {stats['movie_count']}"}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 4},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "success"},
                                "content": [
                                    {"component": "VCardText", "text": f"电视剧: {stats['tv_show_count']}"}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 4},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "info"},
                                "content": [
                                    {"component": "VCardText", "text": f"已看集数: {stats['episode_count']}"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "props": {"class": "mt-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "最近观看"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VList",
                                "props": {"density": "compact"},
                                "content": self._build_recent_list(history)
                            }
                        ]
                    }
                ]
            }
        ]

    def _build_recent_list(self, history: WatchHistory) -> List[Dict]:
        """Build recent watches list items"""
        recent = WatchTrackerUI.build_recent_watches(history, limit=10)
        items = []
        for item in recent:
            if item["type"] == "Movie":
                text = f"🎬 {item['title']}"
            else:
                text = f"📺 {item['title']}"
            items.append({
                "component": "VListItem",
                "props": {"title": text, "subtitle": item.get("watched_at", "")[:10] if item.get("watched_at") else ""}
            })
        return items

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

            # Load movies
            for movie_data in data.get("movies", []):
                history.movies.append(MovieWatchRecord(**movie_data))

            # Load TV shows
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
                    {
                        "id": m.id,
                        "name": m.name,
                        "year": m.year,
                        "watched_at": m.watched_at
                    }
                    for m in history.movies
                ],
                "tv_shows": [
                    {
                        "series_name": tv.series_name,
                        "series_id": tv.series_id,
                        "episodes": [
                            {
                                "id": ep.id,
                                "season": ep.season,
                                "episode": ep.episode,
                                "name": ep.name,
                                "watched_at": ep.watched_at
                            }
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

        try:
            # Load existing history
            history = self._load_history()

            # Get watched items from Emby
            movies = self._emby_client.get_watched_movies(self._user_id)
            episodes = self._emby_client.get_watched_episodes(self._user_id)

            if movies is None:
                logger.error("Failed to fetch movies from Emby")
                return 0, 0

            if episodes is None:
                logger.error("Failed to fetch episodes from Emby")
                return 0, 0

            movies_added = 0
            episodes_added = 0

            # Track existing IDs for deduplication
            existing_movie_ids = {m.id for m in history.movies}

            # Sync movies
            for movie_item in movies:
                if movie_item.played and movie_item.id not in existing_movie_ids:
                    movie_record = MovieWatchRecord(
                        id=movie_item.id,
                        name=movie_item.name,
                        year=movie_item.year,
                        watched_at=movie_item.last_played_date
                    )
                    history.movies.append(movie_record)
                    movies_added += 1

            # Sync episodes
            for episode_item in episodes:
                if episode_item.played:
                    # Check if episode already exists
                    episode_record = EpisodeWatchRecord(
                        id=episode_item.id,
                        season=episode_item.season_number or 0,
                        episode=episode_item.episode_number or 0,
                        name=episode_item.name,
                        watched_at=episode_item.last_played_date
                    )

                    # Find or create series
                    series_name = episode_item.series_name or "Unknown Series"
                    found = False
                    for tv_show in history.tv_shows:
                        if tv_show.series_name == series_name:
                            # Check if episode already exists
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
                        new_tv_show = TvShowWatchRecord(
                            series_name=series_name,
                            series_id=None,
                            episodes=[episode_record]
                        )
                        history.tv_shows.append(new_tv_show)
                        episodes_added += 1

            # Update sync time
            history.last_sync_time = int(__import__("time").time())

            # Save history
            self._save_history(history)

            # Update matcher
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

        # Check if already watched
        message = self._notifier.check_and_notify(title, media_type, year)

        if message:
            # Send notification to user
            self.post_message(
                mtype=NotificationType.Plugin,
                title="Emby观影提醒",
                text=message
            )

    # API endpoints
    def api_sync(self) -> Dict[str, Any]:
        """API: Trigger manual sync"""
        if not self._user_id:
            return {"success": False, "message": "插件未配置"}

        movies, episodes = self._do_sync()
        return {
            "success": True,
            "movies_added": movies,
            "episodes_added": episodes
        }

    def api_stats(self) -> Dict[str, Any]:
        """API: Get watch statistics"""
        history = self._load_history()
        stats = WatchTrackerUI.build_stats(history)
        return {"success": True, "data": stats}

    def api_movies(self) -> Dict[str, Any]:
        """API: Get watched movies list"""
        history = self._load_history()
        movies = WatchTrackerUI.build_movies_list(history)
        return {"success": True, "data": movies}

    def api_tvshows(self) -> Dict[str, Any]:
        """API: Get watched TV shows list"""
        history = self._load_history()
        shows = WatchTrackerUI.build_tv_shows_list(history)
        return {"success": True, "data": shows}

    def api_test_connection(self) -> Dict[str, Any]:
        """API: Test Emby connection"""
        if not self._emby_client:
            return {"success": False, "message": "插件未配置"}

        if self._emby_client.test_connection():
            return {"success": True, "message": "连接成功"}
        else:
            return {"success": False, "message": "连接失败"}
