"""
Emby API Client for Emby Watch Tracker Plugin
"""
import requests
from typing import Optional, List, Dict, Any
import logging

from .models import EmbyUser, EmbyItem

logger = logging.getLogger(__name__)


class EmbyClient:
    """Emby API client with timeout and retry support"""

    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "X-Emby-Token": api_key,
            "Content-Type": "application/json"
        })
        self._user_id: Optional[str] = None
        self._username: Optional[str] = None

    def _request(self, method: str, endpoint: str, timeout: int = 30,
                 retries: int = 3) -> Optional[Any]:
        """
        Make API request with timeout and retry

        :param method: HTTP method
        :param endpoint: API endpoint
        :param timeout: Request timeout in seconds
        :param retries: Number of retries
        :return: Response JSON or None
        """
        url = f"{self.server_url}{endpoint}"
        last_error = None

        for attempt in range(retries):
            try:
                response = self.session.request(method, url, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                last_error = f"Request timeout after {timeout}s"
                logger.warning(f"Emby API timeout (attempt {attempt + 1}/{retries}): {endpoint}")
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(f"Emby API error (attempt {attempt + 1}/{retries}): {e}")

        logger.error(f"Emby API request failed after {retries} attempts: {last_error}")
        return None

    def get_users(self) -> Optional[List[EmbyUser]]:
        """
        Get all users from Emby server

        :return: List of EmbyUser objects
        """
        data = self._request("GET", "/Users")
        if not data:
            return None

        users = []
        for user in data:
            users.append(EmbyUser(
                user_id=user.get("Id", ""),
                username=user.get("Name", "")
            ))
        return users

    def get_user_by_name(self, username: str) -> Optional[EmbyUser]:
        """
        Find user by username

        :param username: Username to search
        :return: EmbyUser or None
        """
        users = self.get_users()
        if not users:
            return None

        for user in users:
            if user.username.lower() == username.lower():
                return user
        return None

    def set_authenticated_user(self, user_id: str, username: str):
        """Set authenticated user for session"""
        self._user_id = user_id
        self._username = username

    def get_watched_items(self, user_id: str,
                          filters: str = "IsPlayed") -> Optional[List[Dict]]:
        """
        Get watched items for a user

        :param user_id: Emby user ID
        :param filters: Filter parameter (default: IsPlayed)
        :return: List of watched items
        """
        endpoint = f"/Users/{user_id}/Items"
        params = {
            "Filters": filters,
            "Recursive": "true",
            "Fields": "ItemIds,Name,Type,SeriesName,SeasonNumber,EpisodeNumber,Year,UserData"
        }

        data = self._request("GET", endpoint, params=params)
        if not data:
            return None

        return data.get("Items", [])

    def get_watched_movies(self, user_id: str) -> List[EmbyItem]:
        """
        Get watched movies for a user

        :param user_id: Emby user ID
        :return: List of EmbyItem objects
        """
        raw_items = self.get_watched_items(user_id)
        if not raw_items:
            return []

        movies = []
        for item in raw_items:
            if item.get("Type") == "Movie":
                user_data = item.get("UserData", {})
                movies.append(EmbyItem(
                    id=item.get("Id", ""),
                    name=item.get("Name", ""),
                    type="Movie",
                    year=item.get("ProductionYear"),
                    played=user_data.get("Played", False),
                    last_played_date=user_data.get("LastPlayedDate")
                ))
        return movies

    def get_watched_episodes(self, user_id: str) -> List[EmbyItem]:
        """
        Get watched episodes for a user

        :param user_id: Emby user ID
        :return: List of EmbyItem objects
        """
        raw_items = self.get_watched_items(user_id)
        if not raw_items:
            return []

        episodes = []
        for item in raw_items:
            if item.get("Type") == "Episode":
                user_data = item.get("UserData", {})
                episodes.append(EmbyItem(
                    id=item.get("Id", ""),
                    name=item.get("Name", ""),
                    type="Episode",
                    series_name=item.get("SeriesName"),
                    season_number=item.get("SeasonNumber"),
                    episode_number=item.get("EpisodeNumber"),
                    played=user_data.get("Played", False),
                    last_played_date=user_data.get("LastPlayedDate")
                ))
        return episodes

    def test_connection(self) -> bool:
        """
        Test connection to Emby server

        :return: True if connection successful
        """
        data = self._request("GET", "/System/Info")
        return data is not None
