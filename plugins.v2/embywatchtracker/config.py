"""
Configuration management for Emby Watch Tracker Plugin
"""
from typing import Optional


class PluginConfig:
    """Plugin configuration"""

    def __init__(self, config: dict = None):
        self._config = config or {}

    @property
    def emby_server_url(self) -> str:
        """Emby server URL"""
        return self._config.get("emby_server_url", "").rstrip("/")

    @property
    def emby_api_key(self) -> str:
        """Emby API key"""
        return self._config.get("emby_api_key", "")

    @property
    def emby_username(self) -> str:
        """Emby username"""
        return self._config.get("emby_username", "")

    @property
    def sync_interval_hours(self) -> int:
        """Sync interval in hours"""
        return int(self._config.get("sync_interval_hours", 6))

    @property
    def enable_notification(self) -> bool:
        """Enable notification for watched media"""
        return self._config.get("enable_notification", True)

    @property
    def fuzzy_match_threshold(self) -> float:
        """Fuzzy match threshold for media matching"""
        return float(self._config.get("fuzzy_match_threshold", 0.9))

    @property
    def enable_incremental_sync(self) -> bool:
        """Enable incremental sync"""
        return self._config.get("enable_incremental_sync", True)

    def is_configured(self) -> bool:
        """Check if plugin is properly configured"""
        return bool(self.emby_server_url and self.emby_api_key and self.emby_username)
