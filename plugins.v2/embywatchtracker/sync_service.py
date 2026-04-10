"""
Synchronization service for Emby Watch Tracker Plugin
"""
import logging
from typing import Tuple

from .emby_client import EmbyClient
from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord, EpisodeWatchRecord

logger = logging.getLogger(__name__)


class SyncService:
    """Service for synchronizing watch history from Emby"""

    def __init__(self, emby_client: EmbyClient):
        self._client = emby_client
        self._history: WatchHistory = WatchHistory()

    def set_history(self, history: WatchHistory):
        """Set the watch history to manage"""
        self._history = history

    def sync_movies(self, user_id: str) -> Tuple[int, list]:
        """
        Sync watched movies from Emby

        :param user_id: Emby user ID
        :return: Tuple of (count_added, list_added)
        """
        movies = self._client.get_watched_movies(user_id)
        if movies is None:
            logger.error("Failed to fetch movies from Emby")
            return 0, []

        movies_added = []
        existing_ids = {m.id for m in self._history.movies}

        for movie_item in movies:
            if movie_item.played and movie_item.id not in existing_ids:
                movie_record = MovieWatchRecord(
                    id=movie_item.id,
                    name=movie_item.name,
                    year=movie_item.year,
                    watched_at=movie_item.last_played_date
                )
                self._history.movies.append(movie_record)
                movies_added.append(movie_record)

        return len(movies_added), movies_added

    def sync_episodes(self, user_id: str) -> Tuple[int, list]:
        """
        Sync watched episodes from Emby

        :param user_id: Emby user ID
        :return: Tuple of (count_added, list_added)
        """
        episodes = self._client.get_watched_episodes(user_id)
        if episodes is None:
            logger.error("Failed to fetch episodes from Emby")
            return 0, []

        episodes_added = []

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

                for tv_show in self._history.tv_shows:
                    if tv_show.series_name == series_name:
                        # Check if episode already exists
                        for existing_ep in tv_show.episodes:
                            if (existing_ep.season == episode_record.season and
                                    existing_ep.episode == episode_record.episode):
                                found = True
                                break
                        if not found:
                            tv_show.episodes.append(episode_record)
                            episodes_added.append((series_name, episode_record))
                        break

                if not found:
                    new_tv_show = TvShowWatchRecord(
                        series_name=series_name,
                        series_id=None,
                        episodes=[episode_record]
                    )
                    self._history.tv_shows.append(new_tv_show)
                    episodes_added.append((series_name, episode_record))

        return len(episodes_added), episodes_added

    def get_movie_count(self) -> int:
        """Get total number of watched movies"""
        return len(self._history.movies)

    def get_tv_show_count(self) -> int:
        """Get total number of watched TV shows"""
        return len(self._history.tv_shows)

    def get_episode_count(self) -> int:
        """Get total number of watched episodes"""
        return sum(len(tv.episodes) for tv in self._history.tv_shows)
