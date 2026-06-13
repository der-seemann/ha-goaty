"""Button platform for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
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
    """Set up reload and per-zone action buttons."""
    domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get("coordinator")
        or runtime_data["coordinator"]
    )
    store = domain_data.get("store") or runtime_data["zone_store"]
    zones = store.get_all().values() if store is not None else []
    entities: list[ButtonEntity] = [GoatyReloadZonesButton(coordinator)]
    entities.extend(GoatyZoneMarkMowedButton(coordinator, store, zone) for zone in zones if zone.get("id"))
    async_add_entities(entities)

    async def _handle_zone_update(zones: list[dict[str, Any]]) -> None:
        existing_ids = {entity.zone_id for entity in entities if hasattr(entity, "zone_id")}
        new_entities = [
            GoatyZoneMarkMowedButton(coordinator, store, zone)
            for zone in zones
            if zone.get("id") and str(zone.get("id")) not in existing_ids
        ]
        if new_entities:
            async_add_entities(new_entities)
            entities.extend(new_entities)

    domain_data.setdefault("zone_update_callbacks", []).append(_handle_zone_update)


class GoatyReloadZonesButton(CoordinatorEntity[GoatyCoordinator], ButtonEntity):
    """Reload the zone list from the mower."""

    _attr_has_entity_name = True
    _attr_name = "Zonen neu laden"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_reload_zones"

    async def async_press(self) -> None:
        await self.hass.services.async_call(DOMAIN, "reload_zones", {}, blocking=True)
        await self.coordinator.async_request_refresh()


class GoatyZoneMarkMowedButton(CoordinatorEntity[GoatyCoordinator], ButtonEntity):
    """Mark one zone as mowed."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:mower"

    def __init__(self, coordinator: GoatyCoordinator, store: Any, zone: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._store = store
        self._zone_id = str(zone.get("id") or "").strip()
        self._zone_name = str(zone.get("name") or self._zone_id).strip()
        self._attr_name = f"{self._zone_name} als gemäht"
        self._attr_unique_id = f"{DOMAIN}_zone_{self._zone_id}_mark_mowed"

    @property
    def zone_id(self) -> str:
        return self._zone_id

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            "mark_zone_mowed",
            {"zone_id": self._zone_id, "advance_angle": True},
            blocking=True,
        )
        await self.coordinator.async_request_refresh()
