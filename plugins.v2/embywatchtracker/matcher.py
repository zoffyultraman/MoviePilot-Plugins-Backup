"""
Media matching logic for Emby Watch Tracker Plugin
"""
import re
from typing import Optional, List, Tuple
from difflib import SequenceMatcher

from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord


class MediaMatcher:
    """Media matching with fuzzy support"""

    def __init__(self, history: WatchHistory, threshold: float = 0.9):
        self._history = history
        self._threshold = threshold

    def _normalize_title(self, title: str) -> str:
        """
        Normalize title for comparison

        :param title: Original title
        :return: Normalized title
        """
        # Remove special characters and convert to lowercase
        title = re.sub(r"[^\w\s]", "", title.lower())
        # Remove extra whitespace
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def _fuzzy_ratio(self, s1: str, s2: str) -> float:
        """
        Calculate fuzzy match ratio

        :param s1: First string
        :param s2: Second string
        :return: Similarity ratio (0-1)
        """
        norm1 = self._normalize_title(s1)
        norm2 = self._normalize_title(s2)
        return SequenceMatcher(None, norm1, norm2).ratio()

    def find_watched_movie(self, title: str, year: Optional[int] = None) \
            -> Optional[MovieWatchRecord]:
        """
        Find if a movie has been watched

        :param title: Movie title
        :param year: Movie year (optional)
        :return: MovieWatchRecord if found
        """
        norm_title = self._normalize_title(title)

        for movie in self._history.movies:
            # Check exact match first
            if self._normalize_title(movie.name) == norm_title:
                return movie

            # Check fuzzy match
            if self._fuzzy_ratio(movie.name, title) >= self._threshold:
                # If year provided, verify year matches
                if year and movie.year and abs(year - movie.year) <= 1:
                    return movie
                elif year and not movie.year:
                    continue
                else:
                    return movie

        return None

    def find_watched_series(self, series_name: str) -> Optional[TvShowWatchRecord]:
        """
        Find if a TV series has been watched

        :param series_name: Series name
        :return: TvShowWatchRecord if found
        """
        norm_series = self._normalize_title(series_name)

        for tv_show in self._history.tv_shows:
            # Check exact match
            if self._normalize_title(tv_show.series_name) == norm_series:
                return tv_show

            # Check fuzzy match
            if self._fuzzy_ratio(tv_show.series_name, series_name) >= self._threshold:
                return tv_show

        return None

    def is_media_watched(self, title: str, media_type: str = "Movie",
                         year: Optional[int] = None) -> Tuple[bool, str]:
        """
        Check if media has been watched

        :param title: Media title
        :param media_type: "Movie" or "Episode"
        :param year: Year for movies
        :return: Tuple of (is_watched, message)
        """
        if media_type == "Movie":
            movie = self.find_watched_movie(title, year)
            if movie:
                msg = f"你已经看过《{title}》"
                if movie.watched_at:
                    msg += f"（{movie.watched_at[:10]}）"
                return True, msg
        else:
            tv_show = self.find_watched_series(title)
            if tv_show:
                msg = f"你已经看过《{title}》"
                if tv_show.episodes:
                    latest = max(tv_show.episodes, key=lambda e: e.watched_at or "")
                    if latest.watched_at:
                        msg += f"（最近观看：{latest.watched_at[:10]}）"
                return True, msg

        return False, ""

    def get_series_episode_count(self, series_name: str) -> int:
        """
        Get number of watched episodes for a series

        :param series_name: Series name
        :return: Number of watched episodes
        """
        tv_show = self.find_watched_series(series_name)
        if tv_show:
            return len(tv_show.episodes)
        return 0
