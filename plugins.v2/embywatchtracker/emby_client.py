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
                 retries: int = 3, params: dict = None) -> Optional[Any]:
        """
        Make API request with timeout and retry

        :param method: HTTP method
        :param endpoint: API endpoint
        :param timeout: Request timeout in seconds
        :param retries: Number of retries
        :param params: Query parameters
        :return: Response JSON or None
        """
        url = f"{self.server_url}{endpoint}"
        # Add api_key to params
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        logger.info(f"Emby API request: {method} {url} params={params}")
        last_error = None

        for attempt in range(retries):
            try:
                response = self.session.request(method, url, timeout=timeout, params=params)
                response.raise_for_status()
                logger.info(f"Emby API response: {response.status_code}")
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
            logger.error("No data returned from /Users endpoint")
            return None

        logger.info(f"Emby /Users returned: {data}")
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
            logger.error(f"No users returned from Emby server")
            return None

        logger.info(f"Looking for user '{username}', available users: {[u.username for u in users]}")
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
            "IsPlayed": "true",
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode",
            "Fields": "ItemIds,Name,Type,SeriesName,SeasonNumber,EpisodeNumber,Year,UserData,ImageTags,SeriesId,ProviderIds"
        }
        logger.info(f"Fetching watched items for user {user_id}")
        data = self._request("GET", endpoint, params=params)
        if not data:
            logger.error("No data returned from get_watched_items")
            return None

        items = data.get("Items", [])
        logger.info(f"get_watched_items returned {len(items)} items")
        return items

    def get_image_url(self, item_id: str, image_type: str = "Primary") -> Optional[str]:
        """
        Get image URL for an item

        :param item_id: Emby item ID
        :param image_type: Type of image (Primary, Backdrop, Logo, etc.)
        :return: Image URL or None
        """
        if not item_id:
            return None
        # Emby image URL format: /Items/{id}/Images/{type}
        # The API returns the image directly, we just need the URL
        return f"{self.server_url}/Items/{item_id}/Images/{image_type}?api_key={self.api_key}"

    def get_item_images(self, item_id: str) -> Optional[Dict]:
        """
        Get image information for an item

        :param item_id: Emby item ID
        :return: Dict with image info or None
        """
        endpoint = f"/Items/{item_id}/Images"
        return self._request("GET", endpoint)

    def get_item(self, item_id: str) -> Optional[Dict]:
        """
        Get full item information from Emby

        :param item_id: Emby item ID
        :return: Item dict or None
        """
        endpoint = f"/Items/{item_id}"
        params = {
            "Fields": "ItemIds,Name,Type,SeriesName,SeasonNumber,EpisodeNumber,Year,UserData,ImageTags,SeriesId,Images"
        }
        return self._request("GET", endpoint, params=params)

    def get_item_image_url(self, item_id: str, image_type: str = "Primary") -> Optional[str]:
        """
        Get valid image URL for an item by checking if image exists

        :param item_id: Emby item ID
        :param image_type: Type of image (Primary, Backdrop, Logo, etc.)
        :return: Image URL or None
        """
        if not item_id:
            return None
        # First check if the item has this image type
        images_info = self.get_item_images(item_id)
        if not images_info:
            return None
        # Images info returns a list of image objects with 'ImageType' field
        for img in images_info:
            if img.get("ImageType") == image_type:
                return f"{self.server_url}/Items/{item_id}/Images/{image_type}?api_key={self.api_key}"
        return None

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
        seen_ids = set()
        for item in raw_items:
            if item.get("Type") == "Movie":
                movie_id = item.get("Id", "")
                if movie_id in seen_ids:
                    continue
                seen_ids.add(movie_id)
                user_data = item.get("UserData", {})
                image_tags = item.get("ImageTags", {})
                # ProviderIds 直接在 item 顶层
                provider_ids = item.get("ProviderIds") or {}
                tmdb_id = provider_ids.get("Tmdb")
                if isinstance(tmdb_id, str):
                    try:
                        tmdb_id = int(tmdb_id)
                    except (ValueError, TypeError):
                        tmdb_id = None
                movies.append(EmbyItem(
                    id=movie_id,
                    name=item.get("Name", ""),
                    type="Movie",
                    year=item.get("ProductionYear"),
                    played=user_data.get("Played", False),
                    last_played_date=user_data.get("LastPlayedDate"),
                    image_id=movie_id if image_tags.get("Primary") else None,
                    tmdb_id=tmdb_id
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
        seen_ids = set()
        for item in raw_items:
            if item.get("Type") == "Episode":
                episode_id = item.get("Id", "")
                # 按id去重
                if episode_id in seen_ids:
                    continue
                seen_ids.add(episode_id)
                user_data = item.get("UserData", {})
                series_id = item.get("SeriesId")
                # ProviderIds 在 item 顶层（用户的示例数据显示）
                provider_ids = item.get("ProviderIds") or {}
                tmdb_id = provider_ids.get("Tmdb")
                if isinstance(tmdb_id, str):
                    try:
                        tmdb_id = int(tmdb_id)
                    except (ValueError, TypeError):
                        tmdb_id = None
                episodes.append(EmbyItem(
                    id=episode_id,
                    name=item.get("Name", ""),
                    type="Episode",
                    series_name=item.get("SeriesName"),
                    series_id=series_id,
                    season_number=item.get("ParentIndexNumber"),
                    episode_number=item.get("IndexNumber"),
                    played=user_data.get("Played", False),
                    last_played_date=user_data.get("LastPlayedDate"),
                    image_id=series_id,
                    tmdb_id=tmdb_id
                ))
        return episodes

    def test_connection(self) -> bool:
        """
        Test connection to Emby server

        :return: True if connection successful
        """
        logger.info("Testing Emby connection...")
        data = self._request("GET", "/System/Info")
        if data is None:
            logger.error("Emby connection test returned no data")
            return False
        logger.info(f"Emby connection test passed: {data.get('ServerName', 'unknown')}")
        return True
