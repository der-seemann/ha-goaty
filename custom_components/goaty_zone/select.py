"""Select platform for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import GoatyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the mowing-zone selector."""
    domain_data = hass.data.get(DOMAIN, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get(entry.entry_id, {}).get("coordinator")
        or runtime_data["coordinator"]
    )
    async_add_entities([GoatyMowZoneSelect(coordinator)])


def _zone_option(zone: dict[str, Any]) -> str:
    zone_id = str(zone.get("id") or "").strip()
    zone_name = str(zone.get("name") or zone_id).strip()
    return f"{zone_id} | {zone_name}" if zone_id else zone_name


class GoatyMowZoneSelect(CoordinatorEntity[GoatyCoordinator], SelectEntity):
    """Select a zone and start mowing it."""

    _attr_has_entity_name = True
    _attr_name = "Mähzone"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_mow_zone"
        self._current_option: str | None = None

    @property
    def options(self) -> list[str]:
        zones = self.coordinator.data.get("zones", []) if self.coordinator.data else []
        options = [_zone_option(zone) for zone in zones if zone.get("id") and zone.get("name")]
        return options or ["Keine Zonen"]

    @property
    def current_option(self) -> str | None:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        if option == "Keine Zonen":
            self._current_option = option
            self.async_write_ha_state()
            return

        zone_id = option.split("|", 1)[0].strip()
        zone_name = option.split("|", 1)[1].strip() if "|" in option else zone_id
        await self.hass.services.async_call(
            DOMAIN,
            "mow_zone",
            {"zone_id": zone_id, "zone_name": zone_name},
            blocking=True,
        )
        self._current_option = option
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
