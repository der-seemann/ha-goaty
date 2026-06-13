"""Sensor platform for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import GoatyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up coordinator-backed Goaty sensors."""
    domain_data = hass.data.get("goaty_zone", {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get(entry.entry_id, {}).get("coordinator")
        or runtime_data["coordinator"]
    )

    entities: list[GoatyCoordinatorSensor] = [
        GoatyMowingWindowSensor(coordinator),
        GoatyDueZonesSensor(coordinator),
        GoatyLockedZonesSensor(coordinator),
        GoatyMowerStateSensor(coordinator),
    ]
    async_add_entities(entities)


class GoatyCoordinatorSensor(CoordinatorEntity[GoatyCoordinator], SensorEntity):
    """Base sensor bound to the Goaty coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoatyCoordinator, key: str, name: str, icon: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"goaty_{key}"

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}


class GoatyMowingWindowSensor(GoatyCoordinatorSensor):
    """Expose mowing window state."""

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator, "mowing_window", "Mähfenster", "mdi:weather-sunset")

    @property
    def native_value(self) -> str:
        window = self._data.get("window", {})
        return "Aktiv" if window.get("active") else "Inaktiv"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        window = self._data.get("window", {})
        return {
            "start": window.get("start", "–"),
            "end": window.get("end", "–"),
            "rain_active": bool(self._data.get("rain_active", False)),
            "lock_reasons": list(self._data.get("lock_reasons", [])),
            "mower_state": self._data.get("mower_state"),
            "updated_at": self._data.get("updated_at"),
        }


class GoatyDueZonesSensor(GoatyCoordinatorSensor):
    """Expose the number of due zones."""

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator, "due_zones", "Fällige Zonen", "mdi:mower-on")

    @property
    def native_value(self) -> int:
        return len(self._data.get("due_zones", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zones = list(self._data.get("due_zones", []))
        return {
            "zones": zones,
            "names": ", ".join(zone.get("name", "") for zone in zones if zone.get("name")),
        }


class GoatyLockedZonesSensor(GoatyCoordinatorSensor):
    """Expose the number of locked zones."""

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator, "locked_zones", "Gesperrte Zonen", "mdi:lock")

    @property
    def native_value(self) -> int:
        return len(self._data.get("locked_zones", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zones = list(self._data.get("locked_zones", []))
        return {
            "zones": zones,
            "names": ", ".join(zone.get("name", "") for zone in zones if zone.get("name")),
        }


class GoatyMowerStateSensor(GoatyCoordinatorSensor):
    """Expose the mower state from Home Assistant."""

    def __init__(self, coordinator: GoatyCoordinator) -> None:
        super().__init__(coordinator, "mower_state", "Mäherstatus", "mdi:mower")

    @property
    def native_value(self) -> str:
        return str(self._data.get("mower_state") or "unavailable")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._data.get("mower_state_attributes", {}))
