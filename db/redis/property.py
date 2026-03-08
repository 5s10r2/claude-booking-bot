"""
db/redis/property.py — Property cache, search results, images, and shortlists.

Covers:
  - Property info map (search results cache)
  - Last search results (24h TTL)
  - Shortlisted properties
  - Property template (WhatsApp carousel)
  - Property image IDs and URLs
  - Property search ID buffer (10-min TTL)
"""

from typing import Optional

from db.redis._base import _r, _json_set, _json_get, PROPERTY_INFO_TTL, SEARCH_IDS_TTL, LAST_SEARCH_TTL


# ---------------------------------------------------------------------------
# Property info map (search results cache)
# ---------------------------------------------------------------------------

def set_property_info_map(user_id: str, info_map: list[dict]) -> None:
    _json_set(f"{user_id}:property_info_map", info_map, ex=PROPERTY_INFO_TTL)


def get_property_info_map(user_id: str) -> list[dict]:
    return _json_get(f"{user_id}:property_info_map", default=[])


# ---------------------------------------------------------------------------
# Last search results (cross-session context, 24h TTL)
# ---------------------------------------------------------------------------

def set_last_search_results(user_id: str, results: list[dict]) -> None:
    _json_set(f"{user_id}:last_search", results, ex=LAST_SEARCH_TTL)


def get_last_search_results(user_id: str) -> list[dict]:
    return _json_get(f"{user_id}:last_search", default=[])


# ---------------------------------------------------------------------------
# Shortlisted properties
# ---------------------------------------------------------------------------

def get_shortlisted_properties(user_id: str) -> list[dict]:
    return _json_get(f"{user_id}:shortlisted", default=[])


# ---------------------------------------------------------------------------
# Property template (carousel cards)
# ---------------------------------------------------------------------------

def save_property_template(user_id: str, template: list[dict]) -> None:
    _json_set(f"{user_id}:property_template", template)


def get_property_template(user_id: str) -> list[dict]:
    return _json_get(f"{user_id}:property_template", default=[])


def clear_property_template(user_id: str) -> None:
    _r().delete(f"{user_id}:property_template")


# ---------------------------------------------------------------------------
# Property images
# ---------------------------------------------------------------------------

def set_property_images_id(user_id: str, images: list[str | None]) -> None:
    _json_set(f"{user_id}:property_images_id", images)


def get_property_images_id(user_id: str) -> list[str | None]:
    return _json_get(f"{user_id}:property_images_id", default=[])


def clear_property_images_id(user_id: str) -> None:
    _r().delete(f"{user_id}:property_images_id")


# ---------------------------------------------------------------------------
# Image URLs
# ---------------------------------------------------------------------------

def set_image_urls(user_id: str, urls: list[str]) -> None:
    _json_set(f"{user_id}:image_urls", urls)


def get_image_urls(user_id: str) -> list[str]:
    return _json_get(f"{user_id}:image_urls", default=[])


def clear_image_urls(user_id: str) -> None:
    _r().delete(f"{user_id}:image_urls")


# ---------------------------------------------------------------------------
# Property search tool IDs (temporary, 10min TTL)
# ---------------------------------------------------------------------------

def set_property_id_for_search(user_id: str, property_ids: list) -> None:
    _json_set(f"{user_id}:search_property_ids", property_ids, ex=SEARCH_IDS_TTL)


def get_property_id_for_search(user_id: str) -> list[str]:
    return _json_get(f"{user_id}:search_property_ids", default=[])


def clear_property_id_for_search(user_id: str) -> None:
    _r().delete(f"{user_id}:search_property_ids")
