"""
Emby Watch Tracker Plugin for MoviePilot V2

Syncs Emby user watch history and provides watch tracking features.
"""
import logging
from typing import Optional, List, Dict, Any, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaServerType
from app.helper.service import ServiceConfigHelper

from .emby_client import EmbyClient
from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord, EpisodeWatchRecord
from .matcher import MediaMatcher
from .notifier import WatchTrackerNotifier
from .ui import WatchTrackerUI

logger = logging.getLogger(__name__)


class EmbyWatchTrackerPlugin(_PluginBase):
    """Emby Watch Tracker Plugin for MoviePilot V2"""

    # Plugin metadata
    plugin_name = "Emby观影追踪"
    plugin_version = "1.0.0"
    plugin_icon = "emby.png"
    plugin_desc = "同步Emby用户观影记录，在MoviePilot中展示已观看媒体"
    plugin_author = "zoffyultraman"
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

    def _get_emby_servers(self) -> List[Dict[str, str]]:
        """
        Get list of configured Emby servers from MoviePilot

        :return: List of server info dicts with name, url, api_key
        """
        servers = []
        try:
            configs = ServiceConfigHelper.get_mediaserver_configs()
            for config in configs:
                if config and config.type == MediaServerType.Emby.value:
                    server_config = config.config or {}
                    servers.append({
                        "name": config.name,
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

        # Load configuration
        self._selected_server = config.get("emby_server", "")
        self._server_url = config.get("emby_server_url", "").rstrip("/")
        self._api_key = config.get("emby_api_key", "")
        self._emby_username = config.get("emby_username", "")
        self._sync_interval_hours = int(config.get("sync_interval_hours", 6))
        self._enable_notification = config.get("enable_notification", True)
        self._fuzzy_threshold = float(config.get("fuzzy_match_threshold", 0.9))
        self._incremental_sync = config.get("enable_incremental_sync", True)

        # If server is selected from MoviePilot config, use that
        if self._selected_server:
            self._use_moviepilot_server(self._selected_server)

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
            configs = ServiceConfigHelper.get_mediaserver_configs()
            config = next((c for c in configs if c.name == server_name), None)
            if not config or config.type != MediaServerType.Emby.value:
                logger.warning(f"Server {server_name} is not an Emby server")
                return False

            server_config = config.config or {}
            self._server_url = server_config.get("url", "").rstrip("/")
            self._api_key = server_config.get("api_key", "")
            return True
        except Exception as e:
            logger.error(f"Failed to use MoviePilot server: {e}")
            return False

    def get_state(self) -> bool:
        """
        Get plugin running state

        :return: True if plugin is configured and running
        """
        return self._emby_client is not None and self._user_id is not None

    def stop_service(self) -> None:
        """Stop plugin service"""
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            self._scheduler = None
        logger.info("Emby Watch Tracker Plugin stopped")

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """
        Get plugin configuration form

        :return: (form config, default values)
        """
        # Get available Emby servers from MoviePilot
        emby_servers = self._get_emby_servers()
        server_items = [{"title": s["name"], "value": s["name"]} for s in emby_servers]
        server_items.insert(0, {"title": "手动输入", "value": ""})

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
                                "component": "VSelect",
                                "props": {
                                    "label": "选择服务器（可选）",
                                    "placeholder": "从MoviePilot配置中选择",
                                    "model": "emby_server",
                                    "items": server_items,
                                    "clearable": True,
                                    "hint": "从MoviePilot已配置的Emby服务器中选择，或手动输入"
                                }
                            }
                        ]
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
            "emby_server": self._selected_server,
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
                "props": {
                    "title": text,
                    "subtitle": (item.get("watched_at", "")[:10] if item.get("watched_at") else "")
                }
            })
        return items

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

        try:
            history = self._load_history()
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

