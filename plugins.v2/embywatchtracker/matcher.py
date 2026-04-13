"""
Media matching logic for Emby Watch Tracker Plugin
"""
import re
import logging
from typing import Optional, List, Tuple
from difflib import SequenceMatcher

from .models import WatchHistory, MovieWatchRecord, TvShowWatchRecord

logger = logging.getLogger(__name__)


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

    def find_watched_movie(self, title: str, year: Optional[int] = None,
                           tmdb_id: Optional[int] = None) -> Optional[MovieWatchRecord]:
        """
        Find if a movie has been watched

        :param title: Movie title
        :param year: Movie year (optional)
        :param tmdb_id: TMDB ID for precise matching (optional)
        :return: MovieWatchRecord if found
        """

        # First try TMDB ID match if available (most precise)
        if tmdb_id:
            for movie in self._history.movies:
                if movie.tmdb_id == tmdb_id:
                    logger.info(f"Matched movie by TMDB ID: {tmdb_id}")
                    return movie

        # Then try title match
        norm_title = self._normalize_title(title)

        for movie in self._history.movies:
            # Check exact match first
            movie_norm = self._normalize_title(movie.name)
            if movie_norm == norm_title:
                logger.info(f"Matched movie by exact title: {movie.name}")
                return movie

            # Check fuzzy match
            if self._fuzzy_ratio(movie.name, title) >= self._threshold:
                # If year provided, verify year matches
                if year and movie.year and abs(year - movie.year) <= 1:
                    logger.info(f"Matched movie by fuzzy match: {movie.name}")
                    return movie
                elif year and not movie.year:
                    continue
                else:
                    logger.info(f"Matched movie by fuzzy match: {movie.name}")
                    return movie

        return None

    def find_watched_series(self, series_name: str,
                            tmdb_id: Optional[int] = None) -> Optional[TvShowWatchRecord]:
        """
        Find if a TV series has been watched

        :param series_name: Series name
        :param tmdb_id: TMDB ID for precise matching (optional)
        :return: TvShowWatchRecord if found
        """
        # First try TMDB ID match if available (most precise)
        if tmdb_id:
            for tv_show in self._history.tv_shows:
                if tv_show.tmdb_id == tmdb_id:
                    logger.info(f"Matched series by TMDB ID: {tmdb_id}")
                    return tv_show

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
                         year: Optional[int] = None,
                         tmdb_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Check if media has been watched

        :param title: Media title
        :param media_type: "Movie" or "Episode"
        :param year: Year for movies
        :param tmdb_id: TMDB ID for precise matching (optional)
        :return: Tuple of (is_watched, message)
        """
        if media_type == "Movie":
            movie = self.find_watched_movie(title, year, tmdb_id)
            if movie:
                msg = f"你已经看过《{title}》"
                if movie.watched_at:
                    msg += f"（{movie.watched_at[:10]}）"
                return True, msg
        else:
            tv_show = self.find_watched_series(title, tmdb_id)
            if tv_show and tv_show.episodes:
                episode_info = self._format_episode_ranges(tv_show.episodes)
                msg = f"你已经看过《{title}》{episode_info}"
                return True, msg

        return False, ""

    def _format_episode_ranges(self, episodes: List) -> str:
        """
        Format episode list into readable ranges by season

        :param episodes: List of EpisodeWatchRecord
        :return: Formatted string like "S01: 1-17, S02: 1-12"
        """
        if not episodes:
            return ""

        # Group by season
        by_season = {}
        for ep in episodes:
            season = ep.season
            if season not in by_season:
                by_season[season] = []
            by_season[season].append(ep.episode)

        # Format each season's episodes as range
        ranges = []
        for season in sorted(by_season.keys()):
            eps = sorted(set(by_season[season]))
            if len(eps) == 1:
                range_str = f"{eps[0]}"
            else:
                # Find contiguous ranges
                range_str = self._compress_episode_list(eps)
            ranges.append(f"S{season:02d}: {range_str}")

        return ", ".join(ranges)

    def _compress_episode_list(self, episodes: List[int]) -> str:
        """
        Compress episode list into ranges

        :param episodes: Sorted list of episode numbers
        :return: String like "1-5, 7, 9-12"
        """
        if not episodes:
            return ""
        if len(episodes) == 1:
            return str(episodes[0])

        ranges = []
        start = episodes[0]
        end = episodes[0]

        for ep in episodes[1:]:
            if ep == end + 1:
                end = ep
            else:
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = end = ep

        # Don't forget the last range
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")

        return ", ".join(ranges)

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
