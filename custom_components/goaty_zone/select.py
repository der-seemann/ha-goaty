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

_FIXED_DIRECTION_OPTIONS = ["Auto", "0°", "45°", "90°", "135°"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the zone and direction selectors."""
    domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    runtime_data = entry.runtime_data or {}
    coordinator: GoatyCoordinator = (
        domain_data.get("coordinator")
        or runtime_data["coordinator"]
    )
    store = domain_data.get("store") or runtime_data["zone_store"]

    zone_select = GoatyZoneSelect(coordinator, entry, store)
    direction_select = GoatyDirectionSelect(coordinator, entry, store, zone_select)
    zone_select.set_direction_select(direction_select)

    domain_data["zone_select"] = zone_select
    domain_data["direction_select"] = direction_select
    async_add_entities([zone_select, direction_select])

    async def _handle_zone_update(_: list[dict[str, Any]]) -> None:
        zone_select.async_write_ha_state()
        direction_select.async_write_ha_state()

    domain_data.setdefault("zone_update_callbacks", []).append(_handle_zone_update)


def _zone_option(zone: dict[str, Any]) -> str:
    zone_id = str(zone.get("id") or "").strip()
    zone_name = str(zone.get("name") or zone_id).strip()
    return f"{zone_id} | {zone_name}" if zone_id else zone_name


def _sort_key(value: str) -> tuple[int, str]:
    value = value.strip()
    return (0, f"{int(value):020d}") if value.isdecimal() else (1, value.casefold())


class GoatyZoneSelect(CoordinatorEntity[GoatyCoordinator], SelectEntity):
    """Select a zone for subsequent operations."""

    _attr_has_entity_name = True
    _attr_name = "Mähzone"
    _attr_icon = "mdi:map-marker"

    def __init__(self, coordinator: GoatyCoordinator, entry: ConfigEntry, store: Any) -> None:
        super().__init__(coordinator)
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_zone_select"
        self._current = "Alle"
        self._direction_select: GoatyDirectionSelect | None = None

    def set_direction_select(self, direction_select: "GoatyDirectionSelect") -> None:
        self._direction_select = direction_select

    @property
    def options(self) -> list[str]:
        zones = self._store.get_all() if self._store is not None else {}
        names = sorted((str(zone.get("name") or "").strip() for zone in zones.values() if zone.get("name")), key=str.casefold)
        return ["Alle", *names]

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_select_option(self, option: str) -> None:
        self._current = option
        self.async_write_ha_state()
        if self._direction_select is not None:
            self._direction_select.reset_for_zone_change()
            self._direction_select.async_write_ha_state()

    def get_selected_zone_id(self) -> str | None:
        """Return the selected zone_id or None for 'Alle'."""
        if self._current == "Alle":
            return None
        zones = self._store.get_all() if self._store is not None else {}
        for zone_id, zone in zones.items():
            if str(zone.get("name") or "").strip() == self._current:
                return str(zone_id)
        return None


class GoatyDirectionSelect(CoordinatorEntity[GoatyCoordinator], SelectEntity):
    """Select the mow direction for the selected zone."""

    _attr_has_entity_name = True
    _attr_name = "Mährichtung"
    _attr_icon = "mdi:compass"

    def __init__(
        self,
        coordinator: GoatyCoordinator,
        entry: ConfigEntry,
        store: Any,
        zone_select: GoatyZoneSelect,
    ) -> None:
        super().__init__(coordinator)
        self._store = store
        self._zone_select = zone_select
        self._attr_unique_id = f"{entry.entry_id}_direction_select"
        self._current = "Auto"

    def reset_for_zone_change(self) -> None:
        self._current = "Auto"

    def _selected_zone(self) -> dict[str, Any] | None:
        zone_id = self._zone_select.get_selected_zone_id()
        if zone_id is None or self._store is None:
            return None
        return self._store.get(zone_id)

    @property
    def options(self) -> list[str]:
        zone = self._selected_zone()
        if not zone:
            return ["Auto"]

        angles = zone.get("angles")
        if not isinstance(angles, list) or not angles:
            angles = [0]

        options = ["Auto"]
        for angle in _FIXED_DIRECTION_OPTIONS[1:]:
            if angle not in options:
                options.append(angle)

        for angle in angles:
            try:
                angle_text = f"{int(angle)}°"
            except (TypeError, ValueError):
                continue
            if angle_text not in options:
                options.append(angle_text)
        return options

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_select_option(self, option: str) -> None:
        zone_id = self._zone_select.get_selected_zone_id()
        if zone_id is None or self._store is None:
            self._current = option
            self.async_write_ha_state()
            return

        if option == "Auto":
            self._current = option
            self.async_write_ha_state()
            return

        zone = self._store.get(zone_id)
        angles = zone.get("angles") if isinstance(zone.get("angles"), list) else [0]
        normalized_angles: list[int] = []
        for angle in angles:
            try:
                normalized_angles.append(int(angle))
            except (TypeError, ValueError):
                continue
        if not normalized_angles:
            normalized_angles = [0]

        try:
            target_angle = int(option.rstrip("°"))
        except ValueError:
            self._current = option
            self.async_write_ha_state()
            return

        try:
            angle_index = normalized_angles.index(target_angle)
        except ValueError:
            self._current = option
            self.async_write_ha_state()
            return

        await self.hass.services.async_call(
            DOMAIN,
            "set_zone_config",
            {"zone_id": zone_id, "angle_index": angle_index},
            blocking=True,
        )
        self._current = option
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
