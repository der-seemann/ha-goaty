"""Button platform for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .coordinator import GoatyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up mower control buttons."""
    domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get("coordinator")
        or runtime_data["coordinator"]
    )
    mower_entity_id = str(entry.data.get("mower_entity_id") or "").strip()
    if not mower_entity_id:
        return

    async_add_entities(
        [
            GoatyPauseButton(entry, mower_entity_id),
            GoatyDockButton(entry, mower_entity_id),
            GoatyMowButton(entry, mower_entity_id, coordinator, domain_data.get("store") or runtime_data["zone_store"]),
        ]
    )


class GoatyPauseButton(ButtonEntity):
    """Pause the mower."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:pause"

    def __init__(self, entry: ConfigEntry, mower_entity_id: str) -> None:
        self._mower = mower_entity_id
        self._attr_unique_id = f"{entry.entry_id}_pause"
        self._attr_name = f"{entry.data.get('device_name', 'Goaty')} Pause"

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            "lawn_mower",
            "pause",
            {"entity_id": self._mower},
            blocking=True,
        )


class GoatyDockButton(ButtonEntity):
    """Dock the mower."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, entry: ConfigEntry, mower_entity_id: str) -> None:
        self._mower = mower_entity_id
        self._attr_unique_id = f"{entry.entry_id}_dock"
        self._attr_name = f"{entry.data.get('device_name', 'Goaty')} Dock"

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            "lawn_mower",
            "dock",
            {"entity_id": self._mower},
            blocking=True,
        )


class GoatyMowButton(ButtonEntity):
    """Start mowing the selected zone or the whole lawn."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:mower-on"

    def __init__(self, entry: ConfigEntry, mower_entity_id: str, coordinator: GoatyCoordinator, store: Any) -> None:
        self._mower = mower_entity_id
        self._coordinator = coordinator
        self._store = store
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mow"
        self._attr_name = f"{entry.data.get('device_name', 'Goaty')} Mähen"

    async def async_press(self) -> None:
        domain_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        zone_select = domain_data.get("zone_select")
        direction_select = domain_data.get("direction_select")

        zone_id = zone_select.get_selected_zone_id() if zone_select else None
        angle = direction_select.get_angle() if direction_select else None

        if zone_id is None:
            await self.hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": self._mower},
                blocking=True,
            )
            return

        zone = self._store.get(zone_id) if self._store is not None else {}
        if angle is None:
            angle = self._store.next_angle(zone_id) if self._store is not None else 0

        await self.hass.services.async_call(
            DOMAIN,
            "mow_zone",
            {
                "zone_id": zone_id,
                "zone_name": zone.get("name", zone_id),
                "angle": angle,
            },
            blocking=True,
        )
