"""
UI components for Emby Watch Tracker Plugin
"""
from typing import List, Dict, Any, Optional

from .models import WatchHistory


class WatchTrackerUI:
    """UI helper for watch tracker"""

    @staticmethod
    def build_movies_list(history: WatchHistory) -> List[Dict[str, Any]]:
        """
        Build movies list for UI display

        :param history: WatchHistory object
        :return: List of movie dictionaries
        """
        movies = []
        for movie in history.movies:
            movies.append({
                "title": movie.name,
                "year": movie.year,
                "watched_at": movie.watched_at[:10] if movie.watched_at else None
            })
        return movies

    @staticmethod
    def build_tv_shows_list(history: WatchHistory) -> List[Dict[str, Any]]:
        """
        Build TV shows list for UI display

        :param history: WatchHistory object
        :return: List of TV show dictionaries
        """
        shows = []
        for tv_show in history.tv_shows:
            shows.append({
                "title": tv_show.series_name,
                "episode_count": len(tv_show.episodes),
                "episodes": [
                    {
                        "season": ep.season,
                        "episode": ep.episode,
                        "name": ep.name,
                        "watched_at": ep.watched_at[:10] if ep.watched_at else None
                    }
                    for ep in sorted(tv_show.episodes,
                                     key=lambda e: (e.season, e.episode))
                ]
            })
        return shows

    @staticmethod
    def build_recent_watches(history: WatchHistory, limit: int = 10) \
            -> List[Dict[str, Any]]:
        """
        Build recent watches list

        :param history: WatchHistory object
        :param limit: Maximum number of items
        :return: List of recent watch items
        """
        recent = []

        # Add movies
        for movie in history.movies:
            if movie.watched_at:
                recent.append({
                    "type": "Movie",
                    "title": movie.name,
                    "watched_at": movie.watched_at
                })

        # Add episodes
        for tv_show in history.tv_shows:
            for ep in tv_show.episodes:
                if ep.watched_at:
                    recent.append({
                        "type": "Episode",
                        "title": f"{tv_show.series_name} S{ep.season:02d}E{ep.episode:02d}",
                        "name": ep.name,
                        "series": tv_show.series_name,
                        "watched_at": ep.watched_at
                    })

        # Sort by watched_at descending
        recent.sort(key=lambda x: x.get("watched_at") or "", reverse=True)

        return recent[:limit]

    @staticmethod
    def build_stats(history: WatchHistory) -> Dict[str, int]:
        """
        Build statistics

        :param history: WatchHistory object
        :return: Statistics dictionary
        """
        return {
            "movie_count": len(history.movies),
            "tv_show_count": len(history.tv_shows),
            "episode_count": sum(len(tv.episodes) for tv in history.tv_shows)
        }
