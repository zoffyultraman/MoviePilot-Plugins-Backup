"""
Storage adapter for Emby Watch Tracker Plugin
This module provides a simple wrapper around the plugin's built-in storage methods.
"""
from typing import Optional

from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord, EpisodeWatchRecord


class WatchHistoryStorage:
    """
    Storage adapter for watch history.

    This class provides a high-level interface for storing watch history,
    delegating actual persistence to the plugin's built-in save_data/get_data methods.
    """

    STORAGE_KEY = "watch_history"

    def __init__(self, plugin_instance):
        """
        Initialize storage with plugin instance

        :param plugin_instance: The plugin instance that provides storage
        """
        self._plugin = plugin_instance

    def load(self) -> WatchHistory:
        """
        Load watch history from storage

        :return: WatchHistory object
        """
        data = self._plugin.get_data(self.STORAGE_KEY)
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
        except Exception:
            return WatchHistory()

    def save(self, history: WatchHistory) -> bool:
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
            self._plugin.save_data(self.STORAGE_KEY, data)
            return True
        except Exception:
            return False
