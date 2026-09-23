"""Default titles for new and existing Light Policy subentries."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .const import (
    CONF_CLASSIFIER_ENTITY,
    SUBENTRY_BATHROOM,
    SUBENTRY_GAMING,
    SUBENTRY_HALLWAY,
    SUBENTRY_MUSIC,
    SUBENTRY_NOTIFICATION_RING,
    SUBENTRY_WAKE_UP,
)

SUBENTRY_DEFAULT_TITLE: dict[str, str] = {
    SUBENTRY_GAMING: "Gaming",
    SUBENTRY_MUSIC: "Musik-Party",
    SUBENTRY_NOTIFICATION_RING: "Notification RGB",
    SUBENTRY_HALLWAY: "Flur",
    SUBENTRY_BATHROOM: "Bad",
    SUBENTRY_WAKE_UP: "Wake-Up",
}


def default_subentry_title(subentry_type: str, data: Mapping[str, Any]) -> str:
    """Use the classifier entity only for Gaming/Music default titles."""
    base = SUBENTRY_DEFAULT_TITLE.get(subentry_type, subentry_type)
    if subentry_type not in (SUBENTRY_GAMING, SUBENTRY_MUSIC):
        return base
    entity = data.get(CONF_CLASSIFIER_ENTITY)
    return f"{base} ({entity.strip()})" if isinstance(entity, str) and entity.strip() else base


def migrated_subentry_title(
    subentry_type: str, title: str, data: Mapping[str, Any]
) -> str | None:
    """Rename only untouched legacy generic titles; preserve custom names."""
    if title != SUBENTRY_DEFAULT_TITLE.get(subentry_type):
        return None
    updated = default_subentry_title(subentry_type, data)
    return updated if updated != title else None


def migrate_subentry_titles(entry: Any, update_subentry: Callable[..., Any]) -> None:
    """Apply the idempotent title migration through HA's subentry API."""
    for subentry in tuple(entry.subentries.values()):
        title = migrated_subentry_title(
            subentry.subentry_type, subentry.title, subentry.data
        )
        if title:
            update_subentry(entry, subentry, title=title)
