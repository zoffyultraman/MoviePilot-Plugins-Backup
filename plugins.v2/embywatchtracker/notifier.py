"""
Notification handling for Emby Watch Tracker Plugin
"""
import logging
from typing import Optional

from .matcher import MediaMatcher

logger = logging.getLogger(__name__)


class WatchTrackerNotifier:
    """Notification handler for watch tracker events"""

    def __init__(self, matcher: MediaMatcher, enabled: bool = True):
        self._matcher = matcher
        self._enabled = enabled
        self._sent_notifications: set = set()

    def check_and_notify(self, title: str, media_type: str = "Movie",
                         year: Optional[int] = None,
                         tmdb_id: Optional[int] = None) -> Optional[str]:
        """
        Check if media has been watched and return notification message

        :param title: Media title
        :param media_type: "Movie" or "Episode"
        :param year: Year for movies
        :param tmdb_id: TMDB ID for precise matching (optional)
        :return: Notification message if watched, None otherwise
        """
        logger.info(f"DEBUG check_and_notify ENTRY: title={title}, media_type={media_type}, year={year}, tmdb_id={tmdb_id}")
        logger.info(f"DEBUG check_and_notify: _enabled={self._enabled}, _matcher={self._matcher}")

        if not self._enabled:
            logger.info("DEBUG check_and_notify: _enabled is False, returning None")
            return None

        # Create unique key to prevent duplicate notifications
        notify_key = f"{media_type}:{title}:{year}:{tmdb_id}"
        logger.info(f"DEBUG check_and_notify: notify_key={notify_key}")

        is_watched, message = self._matcher.is_media_watched(title, media_type, year, tmdb_id)
        logger.info(f"DEBUG check_and_notify: is_watched={is_watched}, message={message}")

        if is_watched and notify_key not in self._sent_notifications:
            self._sent_notifications.add(notify_key)
            logger.info(f"Watch notification triggered for: {title} (TMDB: {tmdb_id})")
            return message

        logger.info("DEBUG check_and_notify: returning None")
        return None

    def clear_notification(self, title: str, media_type: str = "Movie",
                            year: Optional[int] = None):
        """
        Clear notification for media (e.g., when user chooses to re-download)

        :param title: Media title
        :param media_type: "Movie" or "Episode"
        :param year: Year for movies
        """
        notify_key = f"{media_type}:{title}:{year}"
        self._sent_notifications.discard(notify_key)

    def enable(self):
        """Enable notifications"""
        self._enabled = True

    def disable(self):
        """Disable notifications"""
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if notifications are enabled"""
        return self._enabled
