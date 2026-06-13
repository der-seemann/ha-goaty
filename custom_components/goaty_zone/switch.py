"""Switch platform for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up one lock switch per zone."""
    domain_data = hass.data.get(DOMAIN, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get(entry.entry_id, {}).get("coordinator")
        or runtime_data["coordinator"]
    )
    zones = coordinator.data.get("zones", []) if coordinator.data else []
    async_add_entities([GoatyZoneLockSwitch(coordinator, zone) for zone in zones if zone.get("id")])


class GoatyZoneLockSwitch(CoordinatorEntity[GoatyCoordinator], SwitchEntity):
    """Lock or unlock a specific mowing zone."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: GoatyCoordinator, zone: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._zone_id = str(zone.get("id") or "").strip()
        self._zone_name = str(zone.get("name") or self._zone_id).strip()
        self._attr_name = f"{self._zone_name} Sperre"
        self._attr_unique_id = f"{DOMAIN}_zone_{self._zone_id}_lock"

    @property
    def is_on(self) -> bool:
        zones = self.coordinator.data.get("zones", []) if self.coordinator.data else []
        for zone in zones:
            if str(zone.get("id")) == self._zone_id:
                return bool(zone.get("locked"))
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zones = self.coordinator.data.get("zones", []) if self.coordinator.data else []
        for zone in zones:
            if str(zone.get("id")) == self._zone_id:
                return {
                    "zone_id": self._zone_id,
                    "zone_name": zone.get("name"),
                    "locked_until": zone.get("locked_until"),
                    "last_mowed": zone.get("last_mowed"),
                    "due": zone.get("is_due"),
                }
        return {"zone_id": self._zone_id, "zone_name": self._zone_name}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            "lock_zone",
            {"zone_id": self._zone_id},
            blocking=True,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            "unlock_zone",
            {"zone_id": self._zone_id},
            blocking=True,
        )
        await self.coordinator.async_request_refresh()
