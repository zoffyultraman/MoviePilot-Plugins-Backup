"""
Data models for Emby Watch Tracker Plugin
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EmbyUser:
    """Emby user information"""
    user_id: str
    username: str


@dataclass
class MovieWatchRecord:
    """Movie watch record"""
    id: str
    name: str
    year: Optional[int] = None
    watched_at: Optional[str] = None


@dataclass
class EpisodeWatchRecord:
    """TV episode watch record"""
    id: str
    season: int
    episode: int
    name: Optional[str] = None
    watched_at: Optional[str] = None


@dataclass
class TvShowWatchRecord:
    """TV show watch record with aggregated episodes"""
    series_name: str
    series_id: Optional[str] = None
    episodes: List[EpisodeWatchRecord] = field(default_factory=list)


@dataclass
class WatchHistory:
    """Complete watch history storage structure"""
    movies: List[MovieWatchRecord] = field(default_factory=list)
    tv_shows: List[TvShowWatchRecord] = field(default_factory=list)
    last_sync_time: int = 0


@dataclass
class EmbyItem:
    """Emby item from API"""
    id: str
    name: str
    type: str
    series_name: Optional[str] = None
    series_id: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    year: Optional[int] = None
    played: bool = False
    last_played_date: Optional[str] = None
