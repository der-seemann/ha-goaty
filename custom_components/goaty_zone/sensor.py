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
    entry_data = domain_data.setdefault(entry.entry_id, {})
    position_data = entry_data.get("position", {})

    pos_x = GoatyPositionSensor(entry_data, entry.entry_id, "x", "Position X", "cm", position_data)
    pos_y = GoatyPositionSensor(entry_data, entry.entry_id, "y", "Position Y", "cm", position_data)
    pos_heading = GoatyPositionSensor(entry_data, entry.entry_id, "heading", "Position Heading", "°", position_data)

    entities: list[GoatyCoordinatorSensor] = [
        GoatyMowingWindowSensor(coordinator),
        GoatyDueZonesSensor(coordinator),
        GoatyLockedZonesSensor(coordinator),
        GoatyMowerStateSensor(coordinator),
        pos_x,
        pos_y,
        pos_heading,
    ]
    entry_data["position_sensors"] = {"x": pos_x, "y": pos_y, "heading": pos_heading}
    async_add_entities(entities)


class GoatyCoordinatorSensor(CoordinatorEntity[GoatyCoordinator], SensorEntity):
    """Base sensor bound to the Goaty coordinator."""

    _attr_has_entity_name = False

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
        super().__init__(coordinator, "mowing_window", "Goaty Mahfenster", "mdi:weather-sunset")

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
        super().__init__(coordinator, "due_zones", "Goaty Fallige Zonen", "mdi:mower-on")

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
        super().__init__(coordinator, "locked_zones", "Goaty Gesperrte Zonen", "mdi:lock")

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
        super().__init__(coordinator, "mower_state", "Goaty Mahstatus", "mdi:mower")

    @property
    def native_value(self) -> str:
        return str(self._data.get("mower_state") or "unavailable")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._data.get("mower_state_attributes", {}))


class GoatyPositionSensor(SensorEntity):
    """Expose the last known GOAT position."""

    _attr_has_entity_name = False

    def __init__(self, domain_data: dict[str, Any], entry_id: str, axis: str, name: str, unit: str, position_data: dict[str, Any] | None = None) -> None:
        self._domain_data = domain_data
        self._entry_id = entry_id
        self._axis = axis
        self._position_data = dict(position_data or {})
        self._attr_name = f"Goaty {name}"
        self._attr_unique_id = f"{entry_id}_position_{axis}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = "mdi:crosshairs-gps" if axis != "heading" else "mdi:compass-outline"

    def set_position_data(self, position_data: dict[str, Any]) -> None:
        self._position_data = dict(position_data)
        self._domain_data["position"] = self._position_data
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._axis_key() in self._position_data or self._axis_key() in self._domain_data.get("position", {})

    def _axis_key(self) -> str:
        return {
            "x": "robot_x",
            "y": "robot_y",
            "heading": "robot_heading",
        }.get(self._axis, self._axis)

    @property
    def native_value(self) -> float | None:
        source = self._domain_data.get("position", self._position_data)
        value = source.get(self._axis_key())
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        source = self._domain_data.get("position", self._position_data)
        return {
            "source": source.get("source"),
            "updated_at": source.get("updated_at"),
            "robot_state": source.get("robot_state"),
            "robot_battery": source.get("robot_battery"),
            "charger_x": source.get("charger_x"),
            "charger_y": source.get("charger_y"),
        }
