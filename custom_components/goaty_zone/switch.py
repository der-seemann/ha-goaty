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
    domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get("coordinator")
        or runtime_data["coordinator"]
    )
    store = domain_data.get("store") or runtime_data["zone_store"]
    entities: list[GoatyZoneLockSwitch] = [
        GoatyZoneLockSwitch(coordinator, store, zone)
        for zone in (store.get_all().values() if store is not None else [])
        if zone.get("id")
    ]
    async_add_entities(entities)

    async def _handle_zone_update(zones: list[dict[str, Any]]) -> None:
        existing_ids = {entity.zone_id for entity in entities}
        new_entities = [
            GoatyZoneLockSwitch(coordinator, store, zone)
            for zone in zones
            if zone.get("id") and str(zone.get("id")) not in existing_ids
        ]
        if new_entities:
            async_add_entities(new_entities)
            entities.extend(new_entities)

    domain_data.setdefault("zone_update_callbacks", []).append(_handle_zone_update)


class GoatyZoneLockSwitch(CoordinatorEntity[GoatyCoordinator], SwitchEntity):
    """Lock or unlock a specific mowing zone."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: GoatyCoordinator, store: Any, zone: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._store = store
        self._zone_id = str(zone.get("id") or "").strip()
        self._zone_name = str(zone.get("name") or self._zone_id).strip()
        self._attr_name = f"Goaty {self._zone_name} Sperre"
        self._attr_unique_id = f"{DOMAIN}_zone_{self._zone_id}_lock"

    @property
    def zone_id(self) -> str:
        return self._zone_id

    @property
    def is_on(self) -> bool:
        zone = self._store.get(self._zone_id) if self._store is not None else {}
        return bool(zone.get("locked"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._store.get(self._zone_id) if self._store is not None else {}
        return {
            "zone_id": self._zone_id,
            "zone_name": zone.get("name", self._zone_name),
            "locked_until": zone.get("locked_until"),
            "last_mowed": zone.get("last_mowed"),
            "due": zone.get("is_due"),
        }

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
