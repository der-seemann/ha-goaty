"""Goaty zone-control services."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .coordinator import GoatyCoordinator

DOMAIN = "goaty_zone"
ECOVACS_DOMAIN = "ecovacs"
DEFAULT_DEVICE_NAME = "Goaty"
CARD_RESOURCE_PATH = "/local/goaty-zones-card.js"
CARD_SOURCE = "custom_components/goaty_zone/www/goaty-zones-card.js"
MAP_CARD_RESOURCE_PATH = "/local/goaty-map-card.js"
MAP_CARD_SOURCE = "custom_components/goaty_zone/www/goaty-map-card.js"
STORAGE_KEY = "goaty_zone.zone_config"
STORAGE_VERSION = 1
POSITION_DUMP_PATH = Path("/config/goaty_position_live_last.json")
ZONES_TEXT_ENTITY = "input_text.goaty_zones_json"
ZONES_HASH_ENTITY = "input_text.goaty_zones_hash"
ZONES_SELECT_ENTITY = "input_select.goaty_mow_zone"
EMPTY_SELECT_OPTION = "Keine Zonen"

_LOGGER = logging.getLogger(__name__)
GOATY_SENSOR: "GoatyZonesSensor | None" = None
ZONE_STORE: "GoatyZoneStore | None" = None


def _configured_device_name(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        data = entries[0].data or {}
        device_name = str(data.get("device_name") or "").strip()
        if device_name:
            return device_name
        mower_entity_id = str(data.get("mower_entity_id") or "").strip()
        if mower_entity_id:
            return mower_entity_id
    return DEFAULT_DEVICE_NAME


def _card_paths() -> list[tuple[str, str]]:
    return [
        (CARD_RESOURCE_PATH, CARD_SOURCE),
        (MAP_CARD_RESOURCE_PATH, MAP_CARD_SOURCE),
    ]


async def _register_goaty_card_resources(hass: HomeAssistant) -> None:
    for resource_path, source_path in _card_paths():
        www_path = hass.config.path(source_path)
        if not os.path.exists(www_path):
            continue
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(resource_path, www_path, cache_headers=False)]
            )
        except Exception:
            _LOGGER.exception("Failed to register Goaty card static path: %s", resource_path)


class GoatyConfigView(HomeAssistantView):
    """GET /api/goaty_zone/config."""

    url = "/api/goaty_zone/config"
    name = "api:goaty_zone:config"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: Any) -> Any:
        domain_data = self._hass.data.get(DOMAIN, {})
        entry_data = next(iter(domain_data.values()), {}) if isinstance(domain_data, dict) else {}
        cfg = dict(entry_data.get("config") or {})
        cal = dict(cfg.get("calibration") or {})
        return self.json(
            {
                "image_path": cfg.get("image_path"),
                "charger_px_x": cal.get("charger_px_x", 0),
                "charger_px_y": cal.get("charger_px_y", 0),
                "px_per_m_x": cal.get("px_per_m_x", 22.48),
                "px_per_m_y": cal.get("px_per_m_y", 22.48),
                "img_width": cal.get("img_width", 1452),
                "img_height": cal.get("img_height", 2000),
                "position_x_entity": "sensor.goaty_position_x",
                "position_y_entity": "sensor.goaty_position_y",
                "heading_entity": "sensor.goaty_position_heading",
            }
        )


class GoatyPathView(HomeAssistantView):
    """GET /api/goaty_zone/path."""

    url = "/api/goaty_zone/path"
    name = "api:goaty_zone:path"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: Any) -> Any:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        params = request.rel_url.query
        hours_raw = params.get("hours", 24)
        date_str = params.get("date")
        try:
            hours = max(1, int(hours_raw))
        except (TypeError, ValueError):
            hours = 24

        if date_str:
            try:
                day = datetime.fromisoformat(str(date_str))
            except ValueError:
                return self.json({"error": "invalid date"}, status_code=400)
            if day.tzinfo is None:
                day = day.replace(tzinfo=timezone.utc)
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=hours)

        entity_ids = [
            "sensor.goaty_position_x",
            "sensor.goaty_position_y",
            "sensor.goaty_position_heading",
        ]

        try:
            recorder = get_instance(self._hass)
            history = await recorder.async_add_executor_job(
                get_significant_states,
                self._hass,
                start,
                end,
                entity_ids,
                None,
                True,
                False,
                False,
            )
        except Exception:
            _LOGGER.debug("Goaty path history unavailable", exc_info=True)
            return self.json({"points": [], "count": 0, "start": start.isoformat(), "end": end.isoformat()})

        def _timeline(entity_id: str) -> list[tuple[datetime, float]]:
            items: list[tuple[datetime, float]] = []
            for state in history.get(entity_id, []):
                if state.state in ("unknown", "unavailable", None):
                    continue
                try:
                    value = float(state.state)
                except (TypeError, ValueError):
                    continue
                ts = getattr(state, "last_updated", None) or getattr(state, "last_changed", None)
                if ts is None:
                    continue
                items.append((ts, value))
            items.sort(key=lambda item: item[0])
            return items

        x_points = _timeline("sensor.goaty_position_x")
        y_points = _timeline("sensor.goaty_position_y")
        h_points = _timeline("sensor.goaty_position_heading")
        if not x_points or not y_points:
            return self.json({"points": [], "count": 0, "start": start.isoformat(), "end": end.isoformat()})

        y_idx = 0
        h_idx = 0
        points: list[dict[str, Any]] = []

        for ts, x in x_points:
            while y_idx < len(y_points) and y_points[y_idx][0] < ts:
                y_idx += 1
            while h_idx < len(h_points) and h_points[h_idx][0] < ts:
                h_idx += 1
            if y_idx >= len(y_points):
                continue
            y = y_points[y_idx][1]
            h = h_points[h_idx][1] if h_idx < len(h_points) else 0.0
            points.append(
                {
                    "ts": ts.isoformat(),
                    "x": x,
                    "y": y,
                    "h": h,
                }
            )

        return self.json(
            {
                "points": points,
                "count": len(points),
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )


class GoatyZonesSensor(SensorEntity):
    """Store the current GOAT zones as sensor attributes."""

    _attr_name = "Goaty Zonen"
    _attr_icon = "mdi:map-legend"
    _attr_unique_id = "goaty_zones_sensor"
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self) -> None:
        self._zones: list[dict[str, str]] = []
        self._hash = ""
        self._zone_config: dict[str, dict[str, Any]] = {}
        self._attr_native_value = "Keine Zonen"

    @property
    def native_value(self) -> str:
        return f"{len(self._zones)} Zonen" if self._zones else "Keine Zonen"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        enriched_zones = _enrich_zones(self._zones, self._zone_config)
        return {
            "zones": enriched_zones,
            "hash": self._hash,
            "count": len(enriched_zones),
            "due_count": sum(1 for zone in enriched_zones if zone.get("is_due")),
            "zone_names": [zone["name"] for zone in enriched_zones],
            "zone_ids": [zone["id"] for zone in enriched_zones],
        }

    def update_zones(self, zones: list[dict[str, str]], hash_val: str) -> None:
        self._zones = list(zones)
        self._hash = hash_val
        self._attr_native_value = self.native_value
        if self.hass is not None:
            self.async_write_ha_state()

    def update_zone_config(self, config: dict[str, dict[str, Any]]) -> None:
        self._zone_config = {str(zone_id): dict(zone_cfg) for zone_id, zone_cfg in config.items()}
        if self.hass is not None:
            self.async_write_ha_state()


def _normalize_angles(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        return [0]
    normalized: list[int] = []
    for angle in value:
        try:
            normalized.append(int(angle))
        except (TypeError, ValueError):
            continue
    return normalized or [0]


def _enrich_zones(
    zones: list[dict[str, str]],
    zone_config: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    config_map = zone_config if zone_config is not None else (ZONE_STORE.get_all() if ZONE_STORE is not None else {})
    enriched: list[dict[str, Any]] = []
    for zone in zones:
        zone_id = str(zone.get("id", "")).strip()
        zone_name = str(zone.get("name", "")).strip()
        cfg = dict(config_map.get(zone_id, {}))
        angles = _normalize_angles(cfg.get("angles"))
        try:
            angle_index = max(0, int(cfg.get("angle_index", 0))) % len(angles)
        except (TypeError, ValueError):
            angle_index = 0
        enriched.append(
            {
                "id": zone_id,
                "name": zone_name,
                "enabled": cfg.get("enabled", True),
                "frequency_days": cfg.get("frequency_days", 1),
                "angles": angles,
                "current_angle": angles[angle_index],
                "locked": cfg.get("locked", False),
                "locked_until": cfg.get("locked_until"),
                "last_mowed": cfg.get("last_mowed"),
                "is_due": ZONE_STORE.is_due(zone_id) if ZONE_STORE is not None else True,
            }
        )
    return enriched


def _apply_sensor_state(hass: HomeAssistant, zones: list[dict[str, str]], hash_val: str) -> None:
    enriched_zones = _enrich_zones(zones)
    state = f"{len(zones)} Zonen" if zones else "Keine Zonen"
    hass.states.async_set(
        "sensor.goaty_zones",
        state,
        {
            "zones": enriched_zones,
            "hash": hash_val,
            "count": len(enriched_zones),
            "due_count": sum(1 for zone in enriched_zones if zone.get("is_due")),
            "zone_names": [zone["name"] for zone in enriched_zones],
            "zone_ids": [zone["id"] for zone in enriched_zones],
            "source": DOMAIN,
        },
    )


class GoatyZoneStore:
    """Persist GOAT mowing configuration via Home Assistant storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self._data = data if isinstance(data, dict) else {}

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    @staticmethod
    def _default_config(zone_id: str, zone_name: str) -> dict[str, Any]:
        return {
            "name": zone_name,
            "enabled": True,
            "frequency_days": 1,
            "angles": [0],
            "angle_index": 0,
            "last_mowed": None,
            "locked": False,
            "locked_until": None,
        }

    def get(self, zone_id: str) -> dict[str, Any]:
        return dict(self._data.get(str(zone_id), {}))

    def get_all(self) -> dict[str, dict[str, Any]]:
        return {zone_id: dict(config) for zone_id, config in self._data.items()}

    async def async_sync_zone_defaults(self, zones: list[dict[str, str]]) -> bool:
        changed = False
        for zone in zones:
            zone_id = str(zone["id"]).strip()
            zone_name = str(zone["name"]).strip()
            if not zone_id or not zone_name:
                continue
            current = self._data.get(zone_id)
            if current is None:
                self._data[zone_id] = self._default_config(zone_id, zone_name)
                changed = True
                continue

            if current.get("name") != zone_name:
                current["name"] = zone_name
                changed = True
            for key, value in self._default_config(zone_id, zone_name).items():
                if key not in current:
                    current[key] = value
                    changed = True
        if changed:
            await self.async_save()
        return changed

    async def async_update(self, zone_id: str, **kwargs: Any) -> dict[str, Any]:
        zid = str(zone_id).strip()
        if not zid:
            raise ValueError("zone_id is required")
        current = self._data.setdefault(zid, self._default_config(zid, kwargs.get("name", zid)))
        current.update({key: value for key, value in kwargs.items() if value is not None})

        angles = current.get("angles")
        if not isinstance(angles, list) or not angles:
            current["angles"] = [0]
        else:
            normalized_angles: list[int] = []
            for angle in angles:
                try:
                    normalized_angles.append(int(angle))
                except (TypeError, ValueError):
                    continue
            current["angles"] = normalized_angles or [0]

        if "frequency_days" in current:
            try:
                current["frequency_days"] = max(1, int(current["frequency_days"]))
            except (TypeError, ValueError):
                current["frequency_days"] = 1
        if "angle_index" in current:
            try:
                current["angle_index"] = max(0, int(current["angle_index"]))
            except (TypeError, ValueError):
                current["angle_index"] = 0
        if "enabled" in current:
            current["enabled"] = bool(current["enabled"])
        if "locked" in current:
            current["locked"] = bool(current["locked"])

        await self.async_save()
        return dict(current)

    async def async_lock(self, zone_id: str, *, locked_until: str | None = None) -> dict[str, Any]:
        return await self.async_update(zone_id, locked=True, locked_until=locked_until)

    async def async_unlock(self, zone_id: str) -> dict[str, Any]:
        return await self.async_update(zone_id, locked=False, locked_until=None)

    async def async_mark_mowed(
        self,
        zone_id: str,
        *,
        last_mowed: str | None = None,
        advance_angle: bool = True,
    ) -> dict[str, Any]:
        current = self._data.setdefault(str(zone_id), self._default_config(str(zone_id), str(zone_id)))
        current["last_mowed"] = last_mowed or datetime.now(timezone.utc).isoformat()
        if advance_angle:
            await self.async_advance_angle(zone_id)
        await self.async_save()
        return dict(current)

    async def async_reset_timer(self, zone_id: str) -> dict[str, Any]:
        current = self._data.setdefault(str(zone_id), self._default_config(str(zone_id), str(zone_id)))
        current["last_mowed"] = None
        await self.async_save()
        return dict(current)

    async def async_advance_angle(self, zone_id: str) -> dict[str, Any]:
        current = self._data.setdefault(str(zone_id), self._default_config(str(zone_id), str(zone_id)))
        angles = current.get("angles") or [0]
        if not isinstance(angles, list) or not angles:
            angles = [0]
        try:
            idx = int(current.get("angle_index", 0))
        except (TypeError, ValueError):
            idx = 0
        current["angle_index"] = (idx + 1) % len(angles)
        await self.async_save()
        return dict(current)

    def is_due(self, zone_id: str) -> bool:
        cfg = self.get(zone_id)
        if not cfg:
            return True
        if not cfg.get("enabled", True):
            return False
        if cfg.get("locked", False):
            locked_until = cfg.get("locked_until")
            if not locked_until:
                return False
            try:
                until = datetime.fromisoformat(str(locked_until))
            except ValueError:
                return False
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < until.astimezone(timezone.utc):
                return False
        last = cfg.get("last_mowed")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last))
        except ValueError:
            return True
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        try:
            freq_days = max(1, int(cfg.get("frequency_days", 1)))
        except (TypeError, ValueError):
            freq_days = 1
        return datetime.now(timezone.utc) >= last_dt.astimezone(timezone.utc) + timedelta(days=freq_days)

    def next_angle(self, zone_id: str) -> int:
        cfg = self.get(zone_id)
        angles = cfg.get("angles") or [0]
        if not isinstance(angles, list) or not angles:
            return 0
        try:
            idx = int(cfg.get("angle_index", 0)) % len(angles)
        except (TypeError, ValueError):
            idx = 0
        try:
            return int(angles[idx])
        except (TypeError, ValueError, IndexError):
            return 0


def _matches_device(device: Any, wanted: str) -> bool:
    wanted_l = wanted.lower()
    info = getattr(device, "device_info", {}) or {}
    candidates = [
        info.get("nick"),
        info.get("deviceName"),
        info.get("name"),
        info.get("did"),
        info.get("class"),
    ]
    return any(str(value).lower() == wanted_l for value in candidates if value)


def _find_device(hass: HomeAssistant, wanted: str) -> Any:
    entries = hass.config_entries.async_entries(ECOVACS_DOMAIN)
    devices: list[Any] = []
    for entry in entries:
        controller = getattr(entry, "runtime_data", None)
        if controller is None:
            continue
        devices.extend(getattr(controller, "devices", []) or [])

    if not devices:
        raise RuntimeError("No loaded Ecovacs deebot_client devices found")

    for device in devices:
        if _matches_device(device, wanted):
            return device

    for device in devices:
        info = getattr(device, "device_info", {}) or {}
        text = " ".join(str(info.get(key, "")) for key in ("nick", "deviceName", "class"))
        if "goat" in text.lower() or "goaty" in text.lower():
            return device

    names = [getattr(device, "device_info", {}) for device in devices]
    raise RuntimeError(f"No Ecovacs device matching {wanted!r}; available={names!r}")


def _zone_sort_key(zone_id: str) -> tuple[int, str]:
    text = str(zone_id).strip()
    if text.isdecimal():
        return (0, f"{int(text):020d}")
    return (1, text)


def _normalize_subset_list(subsets: Any) -> list[dict[str, str]]:
    zones: dict[str, dict[str, str]] = {}
    if not isinstance(subsets, list):
        return []

    for item in subsets:
        zone_id: Any = None
        zone_name: Any = None

        if isinstance(item, dict):
            zone_id = item.get("mssid") or item.get("id") or item.get("zone_id")
            zone_name = item.get("name") or item.get("zone_name")
        elif isinstance(item, list) and len(item) >= 2:
            if isinstance(item[0], (list, dict)) or isinstance(item[1], (list, dict)):
                zones.update({zone["id"]: zone for zone in _normalize_subset_list(item)})
                continue
            zone_id, zone_name = item[0], item[1]

        if zone_id is None or zone_name is None:
            continue

        zone_id_text = str(zone_id).strip()
        zone_name_text = str(zone_name).strip()
        if not zone_id_text or not zone_name_text:
            continue

        zones.setdefault(zone_id_text, {"id": zone_id_text, "name": zone_name_text})

    return sorted(zones.values(), key=lambda zone: _zone_sort_key(zone["id"]))


def _extract_zones_from_response(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, dict):
        for key in ("subsets", "decoded_subsets"):
            zones = _normalize_subset_list(raw.get(key))
            if zones:
                return zones

        for nested in raw.values():
            zones = _extract_zones_from_response(nested)
            if zones:
                return zones

    elif isinstance(raw, list):
        zones = _normalize_subset_list(raw)
        if zones:
            return zones

        for item in raw:
            zones = _extract_zones_from_response(item)
            if zones:
                return zones

    return []


async def _fetch_zones_from_device(hass: HomeAssistant, device: Any) -> list[dict[str, str]]:
    from deebot_client.commands.json.custom import CustomCommand

    commands: list[tuple[str, Any]] = [("getAreaSet", CustomCommand("getAreaSet"))]

    try:
        from deebot_client.commands.json.map import GetMapSet, GetMapSetV2
        from deebot_client.events.map import MapSetType
    except Exception:
        GetMapSet = None
        GetMapSetV2 = None
        MapSetType = None
    else:
        if GetMapSetV2 is not None and MapSetType is not None:
            commands.append(("GetMapSetV2_ROOMS", GetMapSetV2("", MapSetType.ROOMS)))
        if GetMapSet is not None and MapSetType is not None:
            commands.append(("GetMapSet_ROOMS", GetMapSet("", MapSetType.ROOMS)))

    attempts: list[dict[str, Any]] = []
    for label, command in commands:
        try:
            result = await device.execute_command(command)
            raw = result if isinstance(result, dict) else getattr(result, "raw_response", result)
            zones = _extract_zones_from_response(raw)
            attempts.append({"label": label, "zones": zones})
            if zones:
                return zones
        except Exception as exc:
            attempts.append({"label": label, "error": repr(exc)})

    raise RuntimeError(f"Could not read GOAT zones; attempts={attempts!r}")


def _load_cached_zones_from_dump() -> list[dict[str, str]]:
    dump_path = Path("/config/goaty_zone_areas_last.json")
    if not dump_path.exists():
        return []

    try:
        payload = json.loads(dump_path.read_text())
    except Exception:
        _LOGGER.exception("Failed to read cached GOAT zones dump")
        return []

    zones = _extract_zones_from_response(payload)
    if zones:
        return zones

    attempts = payload.get("attempts") if isinstance(payload, dict) else None
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            zones = _extract_zones_from_response(attempt.get("decoded_subsets"))
            if zones:
                return zones
            zones = _extract_zones_from_response(attempt.get("raw_response"))
            if zones:
                return zones

    return []


async def _load_cached_zones_from_dump_async(hass: HomeAssistant) -> list[dict[str, str]]:
    return await hass.async_add_executor_job(_load_cached_zones_from_dump)


def _load_last_goat_position() -> dict[str, Any]:
    if not POSITION_DUMP_PATH.exists():
        return {}

    try:
        payload = json.loads(POSITION_DUMP_PATH.read_text())
    except Exception:
        _LOGGER.exception("Failed to read Goaty position dump")
        return {}

    body = payload.get("body") if isinstance(payload, dict) else {}
    robot_pos = str(payload.get("robotPos") or body.get("robotPos") or "").strip()
    charger_pos = str(payload.get("chargerPos") or body.get("chargerPos") or "").strip()

    def _parse_triplet(value: str) -> tuple[float | None, float | None, float | None]:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) < 2:
            return None, None, None
        try:
            x = float(parts[0])
            y = float(parts[1])
            heading = float(parts[2]) if len(parts) > 2 else None
            return x, y, heading
        except ValueError:
            return None, None, None

    robot_x, robot_y, robot_heading = _parse_triplet(robot_pos)
    charger_x, charger_y, _ = _parse_triplet(charger_pos)

    return {
        "robot_x": robot_x,
        "robot_y": robot_y,
        "robot_heading": robot_heading,
        "robot_battery": body.get("battery") if isinstance(body, dict) else None,
        "robot_state": body.get("robotState") if isinstance(body, dict) else None,
        "charger_x": charger_x,
        "charger_y": charger_y,
        "source": payload.get("message_name") if isinstance(payload, dict) else None,
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
    }


async def _restore_last_goat_position(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.async_add_executor_job(_load_last_goat_position)


def _slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "goaty"


def _button_card(
    *,
    name: str,
    icon: str,
    service: str,
    data: dict[str, Any] | None = None,
    entity: str | None = None,
    show_state: bool = False,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": "button",
        "name": name,
        "icon": icon,
        "show_state": show_state,
        "tap_action": {
            "action": "call-service",
            "service": service,
            "service_data": data or {},
        },
    }
    if entity:
        card["entity"] = entity
    return card


def _zone_summary_card(zone: dict[str, Any]) -> dict[str, Any]:
    zone_id = str(zone.get("id") or "").strip()
    zone_name = str(zone.get("name") or zone_id).strip() or zone_id
    angle = zone.get("current_angle")
    locked = bool(zone.get("locked"))
    due = bool(zone.get("is_due"))
    last_mowed = zone.get("last_mowed") or "—"
    state_text = "gesperrt" if locked else "frei"
    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "markdown",
                "content": (
                    f"### {zone_name}\n"
                    f"- ID: `{zone_id}`\n"
                    f"- Winkel: `{angle}`\n"
                    f"- Status: `{state_text}`\n"
                    f"- Fällig: `{ 'ja' if due else 'nein' }`\n"
                    f"- Letztes Mähen: `{last_mowed}`"
                ),
            },
            {
                "type": "grid",
                "columns": 3,
                "square": False,
                "cards": [
                    _button_card(
                        name="Mähen",
                        icon="mdi:mower-on",
                        service=f"{DOMAIN}.mow_zone",
                        data={"zone_id": zone_id, "zone_name": zone_name, "angle": angle},
                    ),
                    _button_card(
                        name="Sperren",
                        icon="mdi:lock",
                        service=f"{DOMAIN}.lock_zone",
                        data={"zone_id": zone_id},
                    ),
                    _button_card(
                        name="Freigeben",
                        icon="mdi:lock-open-variant",
                        service=f"{DOMAIN}.unlock_zone",
                        data={"zone_id": zone_id},
                    ),
                ],
            },
        ],
    }


def _build_dashboard(title: str, slug: str, zones: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    mower_entity_id = str(config.get("mower_entity_id") or "").strip()
    mower_entity_id = mower_entity_id or "lawn_mower.goaty"
    enriched_zones = [
        {"id": str(zone_id), **dict(zone)}
        for zone_id, zone in config.get("zones_map", {}).items()
    ] if isinstance(config.get("zones_map"), dict) else zones
    zone_cards = [_zone_summary_card(zone) for zone in enriched_zones] or [
        {
            "type": "markdown",
            "content": "Noch keine Zonen vorhanden. Erst Zonen abrufen, dann Dashboard neu bauen.",
        }
    ]

    zone_buttons = [
        _button_card(
            name="Mähen starten",
            icon="mdi:mower-on",
            service="button.press",
            data={"entity_id": "button.goaty_mahen"},
        ),
    ]

    return {
        "version": 1,
        "strategy": None,
        "title": title,
        "url_path": slug,
        "icon": "mdi:robot-mower",
        "show_in_sidebar": True,
        "mode": "storage",
        "views": [
            {
                "type": "sections",
                "max_columns": 2,
                "title": title,
                "path": slug,
                "icon": "mdi:robot-mower",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "custom:goaty-map-card",
                                "title": title,
                                "hours": 24,
                                "position_update": 15,
                            },
                            {
                                "type": "custom:goaty-zones-card",
                                "title": title,
                                "zones_entity": "sensor.goaty_zones",
                                "mower_entity": mower_entity_id,
                                "mow_domain": DOMAIN,
                                "mow_service": "mow_zone",
                                "reload_domain": DOMAIN,
                                "reload_service": "reload_zones",
                            },
                            {
                                "type": "tile",
                                "entity": mower_entity_id,
                                "name": title,
                                "features": [{"type": "lawn-mower-commands"}],
                            },
                            {
                                "type": "vertical-stack",
                                "cards": [
                                    {
                                        "type": "entities",
                                        "title": "Gezielt mähen",
                                        "show_header_toggle": False,
                                        "entities": [
                                            "select.goaty_mahzone",
                                            "select.goaty_mahrichtung",
                                        ],
                                    },
                                    {
                                        "type": "button",
                                        "name": "Mähen starten",
                                        "icon": "mdi:mower-on",
                                        "tap_action": {
                                            "action": "call-service",
                                            "service": "button.press",
                                            "service_data": {"entity_id": "button.goaty_mahen"},
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "entities",
                                "title": "Mähautomatik",
                                "show_header_toggle": False,
                                "entities": [
                                    {"entity": "sensor.goaty_mahfenster", "name": "Mähfenster"},
                                    {"entity": "sensor.goaty_fallige_zonen", "name": "Fällige Zonen"},
                                    {"entity": "sensor.goaty_gesperrte_zonen", "name": "Gesperrte Zonen"},
                                    {"entity": "sensor.goaty_mahstatus", "name": "Status"},
                                    {"entity": "sensor.goaty_position_x", "name": "Position X"},
                                    {"entity": "sensor.goaty_position_y", "name": "Position Y"},
                                    {"entity": "sensor.goaty_position_heading", "name": "Heading"},
                                ],
                            },
                            {
                                "type": "entities",
                                "title": "Wartung",
                                "show_header_toggle": False,
                                "entities": [
                                    {"entity": "input_text.goaty_current_zone_name", "name": "Aktive Zone"},
                                    {"entity": "input_text.goaty_current_zone_id", "name": "Aktive Zone ID"},
                                    {"entity": "input_boolean.goaty_zone_active", "name": "Zonenmodus"},
                                ],
                            },
                        ],
                    },
                    {
                        "type": "grid",
                        "cards": zone_cards,
                    },
                    {
                        "type": "grid",
                        "cards": [
                            _button_card(
                                name="Zonen abrufen",
                                icon="mdi:download",
                                service=f"{DOMAIN}.get_zones",
                                data={},
                            ),
                            _button_card(
                                name="Dashboard neu bauen",
                                icon="mdi:view-dashboard",
                                service=f"{DOMAIN}.create_dashboard",
                                data={"dashboard_title": title, "overwrite": True},
                            ),
                            _button_card(
                                name="Mähzonen laden",
                                icon="mdi:reload",
                                service=f"{DOMAIN}.reload_zones",
                                data={},
                            ),
                        ],
                    },
                ],
            }
        ],
    }


def _zones_hash(zones: list[dict[str, str]]) -> str:
    new_json = json.dumps(sorted(zones, key=lambda zone: _zone_sort_key(zone["id"])), ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(new_json.encode("utf-8")).hexdigest()[:8]


async def _write_input_text_value(
    hass: HomeAssistant,
    entity_id: str,
    value: str,
    *,
    context: Any | None = None,
) -> None:
    if hass.states.get(entity_id) is not None:
        try:
            await hass.services.async_call(
                "input_text",
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
                context=context,
            )
            return
        except Exception:
            _LOGGER.exception("Failed to update %s via input_text service; falling back to state machine", entity_id)

    hass.states.async_set(entity_id, value, {"source": DOMAIN})


async def _notify_zone_update(hass: HomeAssistant, *, changed: bool, zones: list[dict[str, str]], new_hash: str) -> None:
    lines = [f"{len(zones)} Zonen {'geladen (geändert)' if changed else 'geladen (keine Änderung)'}."]
    if zones:
        lines.extend(f"- {zone['id']} | {zone['name']}" for zone in zones)
    lines.append(f"Hash: {new_hash}")
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": f"Goaty - Zonen {'aktualisiert' if changed else 'unverändert'}",
            "message": "\n".join(lines),
            "notification_id": "goaty_zones_update",
        },
        blocking=True,
    )


async def _write_input_select_options(
    hass: HomeAssistant,
    entity_id: str,
    options: list[str],
    *,
    context: Any | None = None,
) -> None:
    current_state = hass.states.get(entity_id)
    current_value = current_state.state if current_state is not None else None
    effective_options = options if options else [EMPTY_SELECT_OPTION]
    desired_value = current_value if current_value in effective_options else effective_options[0]

    if current_state is not None:
        try:
            await hass.services.async_call(
                "input_select",
                "set_options",
                {"entity_id": entity_id, "options": effective_options},
                blocking=True,
                context=context,
            )
            await hass.services.async_call(
                "input_select",
                "select_option",
                {"entity_id": entity_id, "option": desired_value},
                blocking=True,
                context=context,
            )
            return
        except Exception:
            _LOGGER.exception("Failed to update %s via input_select service; falling back to state machine", entity_id)

    hass.states.async_set(entity_id, desired_value, {"options": effective_options, "source": DOMAIN})


async def _store_zones(
    hass: HomeAssistant,
    zones: list[dict[str, str]],
    *,
    force_update: bool,
    context: Any | None = None,
) -> tuple[bool, str]:
    normalized_zones = sorted(zones, key=lambda zone: _zone_sort_key(zone["id"]))
    new_hash = _zones_hash(normalized_zones)
    stored_state = hass.states.get(ZONES_HASH_ENTITY)
    stored_hash = stored_state.state if stored_state is not None else ""
    changed = force_update or stored_hash != new_hash

    # Keep the old helper as a compact debug trail; the sensor is the real source of truth now.
    await _write_input_text_value(
        hass,
        ZONES_TEXT_ENTITY,
        f"{len(normalized_zones)} Zonen | hash={new_hash}",
        context=context,
    )
    await _write_input_text_value(hass, ZONES_HASH_ENTITY, new_hash, context=context)
    await _write_input_select_options(
        hass,
        ZONES_SELECT_ENTITY,
        sorted([zone["name"] for zone in normalized_zones], key=str.casefold),
        context=context,
    )

    if ZONE_STORE is not None:
        await ZONE_STORE.async_sync_zone_defaults(normalized_zones)
    if GOATY_SENSOR is not None:
        GOATY_SENSOR.update_zones(normalized_zones, new_hash)
        if ZONE_STORE is not None:
            GOATY_SENSOR.update_zone_config(ZONE_STORE.get_all())
    _apply_sensor_state(hass, normalized_zones, new_hash)
    await _notify_zone_update_callbacks(hass, normalized_zones)

    await _notify_zone_update(hass, changed=changed, zones=normalized_zones, new_hash=new_hash)
    return changed, new_hash


async def _handle_get_zones_impl(
    hass: HomeAssistant,
    call: ServiceCall,
    *,
    force_update: bool,
) -> None:
    device_name = str(call.data.get("device_name") or _configured_device_name(hass)).strip()
    device = _find_device(hass, device_name)
    source = "device"
    try:
        zones = await _fetch_zones_from_device(hass, device)
    except Exception as exc:
        _LOGGER.warning("GOAT zone fetch failed from device, trying cached dump: %s", exc)
        zones = await _load_cached_zones_from_dump_async(hass)
        source = "cache"
        if not zones:
            raise
    changed, new_hash = await _store_zones(
        hass,
        zones,
        force_update=force_update,
        context=call.context,
    )
    _LOGGER.info(
        "GOAT zones %s from %s (%s, hash=%s, count=%d)",
        "updated" if changed else "unchanged",
        source,
        "forced" if force_update else "compared",
        new_hash,
        len(zones),
    )


def _build_clean_area_command(zone_id: str, *, angle: int | None = None) -> Any:
    from deebot_client.commands.json.clean import CleanAreaV2
    from deebot_client.models import CleanMode

    # The clean command signature differs across deebot_client releases.
    # Try the most specific form first, then fall back to the older one.
    if angle is not None:
        for args in (
            (CleanMode.SPOT_AREA, [int(zone_id)], 1, angle),
            (CleanMode.SPOT_AREA, [int(zone_id)], 1),
        ):
            try:
                return CleanAreaV2(*args)
            except TypeError:
                continue
    return CleanAreaV2(CleanMode.SPOT_AREA, [int(zone_id)], 1)


async def _send_mow_command(hass: HomeAssistant, zone_id: str, *, angle: int | None = None, device_name: str = DEFAULT_DEVICE_NAME) -> None:
    device = _find_device(hass, device_name)
    command = _build_clean_area_command(zone_id, angle=angle)
    await device.execute_command(command)


async def _handle_mow_zone_impl(hass: HomeAssistant, call: ServiceCall) -> None:
    zone_id = str(call.data["zone_id"]).strip()
    if not zone_id or not zone_id.isdecimal():
        raise ValueError("zone_id must be a decimal Ecovacs zone ID, e.g. 133")

    zone_name = str(call.data.get("zone_name", "")).strip()
    device_name = str(call.data.get("device_name") or _configured_device_name(hass)).strip()
    angle_value = call.data.get("angle")
    if angle_value is None:
        angle = ZONE_STORE.next_angle(zone_id) if ZONE_STORE is not None else 0
    else:
        try:
            angle = int(angle_value)
        except (TypeError, ValueError):
            angle = ZONE_STORE.next_angle(zone_id) if ZONE_STORE is not None else 0
    device = _find_device(hass, device_name)
    info = getattr(device, "device_info", {}) or {}
    _LOGGER.warning(
        "Starting GOAT zone_id=%s zone_name=%s angle=%s on Ecovacs device nick=%s class=%s",
        zone_id,
        zone_name or "-",
        angle,
        info.get("nick"),
        info.get("class"),
    )
    await _send_mow_command(hass, zone_id, angle=angle, device_name=device_name)

    if hass.states.get("input_text.goaty_current_zone_id") is not None:
        await hass.services.async_call(
            "input_text",
            "set_value",
            {"entity_id": "input_text.goaty_current_zone_id", "value": zone_id},
            blocking=True,
            context=call.context,
        )
    if zone_name and hass.states.get("input_text.goaty_current_zone_name") is not None:
        await hass.services.async_call(
            "input_text",
            "set_value",
            {"entity_id": "input_text.goaty_current_zone_name", "value": zone_name},
            blocking=True,
            context=call.context,
        )
    if hass.states.get("input_boolean.goaty_zone_active") is not None:
        await hass.services.async_call(
            "input_boolean",
            "turn_on",
            {"entity_id": "input_boolean.goaty_zone_active"},
            blocking=True,
            context=call.context,
        )


async def _restore_sensor_from_cache(hass: HomeAssistant) -> None:
    cached = await _load_cached_zones_from_dump_async(hass)
    if cached:
        new_hash = _zones_hash(cached)
        if ZONE_STORE is not None:
            await ZONE_STORE.async_sync_zone_defaults(cached)
        if GOATY_SENSOR is not None and GOATY_SENSOR.hass is not None:
            GOATY_SENSOR.update_zones(cached, new_hash)
            if ZONE_STORE is not None:
                GOATY_SENSOR.update_zone_config(ZONE_STORE.get_all())
            _apply_sensor_state(GOATY_SENSOR.hass, cached, new_hash)
        else:
            # Fallback if the entity platform is not available.
            _apply_sensor_state(hass, cached, new_hash)


def _zone_config_response(zone_id: str | None = None) -> dict[str, Any]:
    if ZONE_STORE is None:
        return {}
    if zone_id is None:
        return ZONE_STORE.get_all()
    return ZONE_STORE.get(zone_id)


async def _refresh_sensor_from_known_zones(hass: HomeAssistant) -> None:
    current_state = hass.states.get("sensor.goaty_zones")
    zones: list[dict[str, str]] = []

    if current_state is not None:
        raw_zones = current_state.attributes.get("zones")
        if isinstance(raw_zones, list):
            zones = _normalize_subset_list(raw_zones)

    if not zones:
        zones_state = hass.states.get(ZONES_TEXT_ENTITY)
        if zones_state is not None:
            raw_text = zones_state.state.strip()
            if raw_text:
                try:
                    parsed = json.loads(raw_text)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    zones = _normalize_subset_list(parsed)
                elif isinstance(parsed, dict):
                    zones = _extract_zones_from_response(parsed)

    if not zones:
        zones = await _load_cached_zones_from_dump_async(hass)

    if zones and ZONE_STORE is not None:
        await ZONE_STORE.async_sync_zone_defaults(zones)
        if GOATY_SENSOR is not None:
            GOATY_SENSOR.update_zone_config(ZONE_STORE.get_all())
        _apply_sensor_state(hass, zones, _zones_hash(zones))
        await _notify_zone_update_callbacks(hass, zones)


async def _notify_zone_update_callbacks(hass: HomeAssistant, zones: list[dict[str, str]]) -> None:
    """Notify registered dynamic zone listeners."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return

    for entry_data in domain_data.values():
        if not isinstance(entry_data, dict):
            continue
        callbacks = entry_data.get("zone_update_callbacks") or []
        for callback in list(callbacks):
            try:
                result = callback(zones)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.debug("Goaty zone update callback failed", exc_info=True)


async def _refresh_coordinators(hass: HomeAssistant) -> None:
    """Refresh all Goaty coordinators after storage changes."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return

    for entry_data in domain_data.values():
        if not isinstance(entry_data, dict):
            continue
        coordinator = entry_data.get("coordinator")
        if coordinator is None:
            continue
        try:
            await coordinator.async_request_refresh()
        except Exception:
            _LOGGER.debug("Failed to refresh Goaty coordinator", exc_info=True)


def _dashboard_store_key(slug: str) -> str:
    return f"lovelace.{slug}"


def _register_goaty_dashboard(
    hass: HomeAssistant, slug: str, dashboard_config: dict[str, Any], update: bool
) -> None:
    """Register or update the Goaty panel in Lovelace."""
    lovelace_data = hass.data.get("lovelace")
    dashboards = getattr(lovelace_data, "dashboards", None)
    if isinstance(dashboards, dict):
        storage_config = {**dashboard_config, "id": slug, "url_path": slug}
        dashboards[slug] = lovelace_dashboard.LovelaceStorage(hass, storage_config)

    frontend.async_register_built_in_panel(
        hass,
        DOMAIN,
        frontend_url_path=slug,
        require_admin=bool(dashboard_config.get("require_admin", False)),
        show_in_sidebar=bool(dashboard_config.get("show_in_sidebar", True)),
        sidebar_title=str(dashboard_config.get("title") or DEFAULT_DEVICE_NAME),
        sidebar_icon=str(dashboard_config.get("icon") or "mdi:robot-mower"),
        config={"mode": "storage"},
        update=update,
    )


async def _load_existing_dashboard(hass: HomeAssistant, slug: str) -> dict[str, Any] | None:
    store = Store(hass, 1, _dashboard_store_key(slug))
    loaded = await store.async_load()
    return loaded if isinstance(loaded, dict) else None


async def _save_dashboard(
    hass: HomeAssistant, slug: str, dashboard: dict[str, Any], update: bool
) -> None:
    store = Store(hass, 1, _dashboard_store_key(slug))
    await store.async_save(dashboard)
    _register_goaty_dashboard(hass, slug, dashboard, update)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register Goaty zone services and sensor."""

    global GOATY_SENSOR, ZONE_STORE

    GOATY_SENSOR = None

    ZONE_STORE = GoatyZoneStore(hass)
    await ZONE_STORE.async_load()

    await _register_goaty_card_resources(hass)
    hass.http.register_view(GoatyConfigView(hass))
    hass.http.register_view(GoatyPathView(hass))

    await _restore_sensor_from_cache(hass)

    async def handle_get_zones(call: ServiceCall) -> None:
        await _handle_get_zones_impl(hass, call, force_update=True)

    async def handle_reload_zones(call: ServiceCall) -> None:
        await _handle_get_zones_impl(hass, call, force_update=False)

    async def handle_mow_zone(call: ServiceCall) -> None:
        await _handle_mow_zone_impl(hass, call)

    async def handle_get_zone_config(call: ServiceCall) -> dict[str, Any]:
        zone_id = call.data.get("zone_id")
        if zone_id:
            result = _zone_config_response(str(zone_id))
            _LOGGER.info("GOAT zone config requested for zone_id=%s -> %s", zone_id, result)
            return result
        result = _zone_config_response()
        _LOGGER.info("GOAT zone config requested for all zones (%d entries)", len(result))
        return result

    async def handle_set_zone_config(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {}
        zone_id = str(call.data["zone_id"]).strip()
        payload: dict[str, Any] = {}
        for key in (
            "name",
            "enabled",
            "frequency_days",
            "angles",
            "angle_index",
            "last_mowed",
            "locked",
            "locked_until",
        ):
            if key in call.data:
                payload[key] = call.data[key]
        result = await ZONE_STORE.async_update(zone_id, **payload)
        await _refresh_sensor_from_known_zones(hass)
        await _refresh_coordinators(hass)
        _LOGGER.info("GOAT zone config updated for zone_id=%s -> %s", zone_id, result)
        return result

    async def handle_lock_zone(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {}
        zone_id = str(call.data["zone_id"]).strip()
        locked_until = call.data.get("until") or call.data.get("locked_until")
        result = await ZONE_STORE.async_lock(zone_id, locked_until=locked_until)
        await _refresh_sensor_from_known_zones(hass)
        await _refresh_coordinators(hass)
        _LOGGER.info("GOAT zone locked for zone_id=%s -> %s", zone_id, result)
        return result

    async def handle_unlock_zone(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {}
        zone_id = str(call.data["zone_id"]).strip()
        result = await ZONE_STORE.async_unlock(zone_id)
        await _refresh_sensor_from_known_zones(hass)
        await _refresh_coordinators(hass)
        _LOGGER.info("GOAT zone unlocked for zone_id=%s -> %s", zone_id, result)
        return result

    async def handle_reset_zone_timer(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {}
        zone_id = str(call.data["zone_id"]).strip()
        result = await ZONE_STORE.async_reset_timer(zone_id)
        await _refresh_sensor_from_known_zones(hass)
        await _refresh_coordinators(hass)
        _LOGGER.info("GOAT zone timer reset for zone_id=%s -> %s", zone_id, result)
        return result

    async def handle_mark_zone_mowed(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {}
        zone_id = str(call.data["zone_id"]).strip()
        last_mowed = call.data.get("last_mowed")
        advance_angle = bool(call.data.get("advance_angle", True))
        result = await ZONE_STORE.async_mark_mowed(zone_id, last_mowed=last_mowed, advance_angle=advance_angle)
        await _refresh_sensor_from_known_zones(hass)
        await _refresh_coordinators(hass)
        _LOGGER.info("GOAT zone marked mowed for zone_id=%s -> %s", zone_id, result)
        return result

    async def handle_get_due_zones(call: ServiceCall) -> dict[str, Any]:
        if ZONE_STORE is None:
            return {"due_zones": [], "count": 0}
        due_zones: list[dict[str, Any]] = []
        for zone_id, cfg in ZONE_STORE.get_all().items():
            if not ZONE_STORE.is_due(zone_id):
                continue
            due_zones.append({"id": zone_id, **cfg, "is_due": True, "current_angle": ZONE_STORE.next_angle(zone_id)})
        result = {"due_zones": due_zones, "count": len(due_zones)}
        _LOGGER.info("GOAT due zones requested -> %s", result)
        return result

    async def handle_create_dashboard(call: ServiceCall) -> None:
        if ZONE_STORE is None:
            return None
        title = str(call.data.get("dashboard_title") or DEFAULT_DEVICE_NAME).strip() or DEFAULT_DEVICE_NAME
        slug = "goaty"
        overwrite = bool(call.data.get("overwrite", False))
        config = {}
        domain_data = hass.data.get(DOMAIN)
        if isinstance(domain_data, dict):
            for entry_data in domain_data.values():
                if isinstance(entry_data, dict) and isinstance(entry_data.get("config"), dict):
                    config = dict(entry_data["config"])
                    break
        zones_map = ZONE_STORE.get_all()
        zones = [{"id": zone_id, **dict(zone)} for zone_id, zone in zones_map.items()]
        config["zones_map"] = zones_map
        dashboard = _build_dashboard(title, slug, zones, config)
        existing = await _load_existing_dashboard(hass, slug)
        if existing and not overwrite:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Goaty Dashboard",
                    "message": (
                        f"Dashboard '{slug}' existiert bereits. "
                        "Setze overwrite: true, um es zu überschreiben."
                    ),
                    "notification_id": "goaty_dashboard_exists",
                },
                blocking=True,
            )
            return None

        await _save_dashboard(hass, slug, dashboard, bool(existing))
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Goaty Dashboard erstellt",
                "message": (
                    f"Dashboard '{title}' wurde mit {len(zones)} Zonen erstellt. "
                    "Browser neu laden."
                ),
                "notification_id": "goaty_dashboard_created",
                },
                blocking=True,
            )
        return None

    hass.services.async_register(DOMAIN, "get_zones", handle_get_zones, schema=vol.Schema({}))
    hass.services.async_register(
        DOMAIN,
        "mow_zone",
        handle_mow_zone,
        schema=vol.Schema(
            {
                vol.Required("zone_id"): cv.string,
                vol.Optional("zone_name", default=""): cv.string,
                vol.Optional("device_name", default=DEFAULT_DEVICE_NAME): cv.string,
                vol.Optional("angle"): vol.Coerce(int),
            }
        ),
    )
    hass.services.async_register(DOMAIN, "reload_zones", handle_reload_zones, schema=vol.Schema({}))
    hass.services.async_register(
        DOMAIN,
        "get_zone_config",
        handle_get_zone_config,
        schema=vol.Schema({vol.Optional("zone_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "set_zone_config",
        handle_set_zone_config,
        schema=vol.Schema(
            {
                vol.Required("zone_id"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("enabled"): cv.boolean,
                vol.Optional("frequency_days"): vol.All(int, vol.Range(min=1, max=30)),
                vol.Optional("angles"): [vol.All(int, vol.Range(min=0, max=180))],
                vol.Optional("angle_index"): vol.All(int, vol.Range(min=0)),
                vol.Optional("last_mowed"): cv.string,
                vol.Optional("locked"): cv.boolean,
                vol.Optional("locked_until"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "lock_zone",
        handle_lock_zone,
        schema=vol.Schema(
            {
                vol.Required("zone_id"): cv.string,
                vol.Optional("until"): cv.string,
                vol.Optional("locked_until"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "unlock_zone",
        handle_unlock_zone,
        schema=vol.Schema({vol.Required("zone_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "reset_zone_timer",
        handle_reset_zone_timer,
        schema=vol.Schema({vol.Required("zone_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "mark_zone_mowed",
        handle_mark_zone_mowed,
        schema=vol.Schema(
            {
                vol.Required("zone_id"): cv.string,
                vol.Optional("last_mowed"): cv.string,
                vol.Optional("advance_angle", default=True): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_due_zones",
        handle_get_due_zones,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "create_dashboard",
        handle_create_dashboard,
        schema=vol.Schema(
            {
                vol.Optional("dashboard_title", default=DEFAULT_DEVICE_NAME): cv.string,
                vol.Optional("overwrite", default=False): cv.boolean,
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the config entry and forward entity platforms."""
    global VIEWS_REGISTERED
    if ZONE_STORE is None:
        raise RuntimeError("Goaty zone store not initialized")

    coordinator = GoatyCoordinator(hass, entry, ZONE_STORE)
    await coordinator.async_config_entry_first_refresh()
    position = await _restore_last_goat_position(hass)

    entry.runtime_data = {
        "coordinator": coordinator,
        "zone_store": ZONE_STORE,
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "config": dict(entry.data),
        "coordinator": coordinator,
        "store": ZONE_STORE,
        "position": position,
        "zone_update_callbacks": [],
    }
    await hass.config_entries.async_forward_entry_setups(
        entry,
        [Platform.SENSOR, Platform.SELECT, Platform.SWITCH, Platform.BUTTON],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        [Platform.SENSOR, Platform.SELECT, Platform.SWITCH, Platform.BUTTON],
    )
    domain_data = hass.data.get(DOMAIN)
    if isinstance(domain_data, dict):
        domain_data.pop(entry.entry_id, None)
    if hasattr(entry, "runtime_data"):
        entry.runtime_data = None
    return unload_ok
