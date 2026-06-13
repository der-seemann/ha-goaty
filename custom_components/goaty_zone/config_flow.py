"""Config flow for Goaty Zone Control."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from . import DOMAIN

CONF_MOWER_ENTITY_ID = "mower_entity_id"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_IMAGE_SOURCE = "image_source"
CONF_IMAGE_PATH = "image_path"
CONF_IMAGE_SOURCE_URL = "image_source_url"
CONF_CALIBRATION = "calibration"
CONF_TIME_WINDOW = "time_window"
DEVICE_DOMAIN = "lawn_mower"
DEFAULT_IMAGE_FILENAME = "goaty_luftbild.jpg"
DEFAULT_IMAGE_PATH = f"/local/{DEFAULT_IMAGE_FILENAME}"
DEFAULT_CHARGER_LAT = 51.06321
DEFAULT_CHARGER_LON = 11.89711
DEFAULT_MIN_LAT = 51.062665
DEFAULT_MAX_LAT = 51.063465
DEFAULT_MIN_LON = 11.896489
DEFAULT_MAX_LON = 11.897411
DEFAULT_IMG_WIDTH = 1452
DEFAULT_IMG_HEIGHT = 2000
DEFAULT_START_MODE = "sun"
DEFAULT_START_OFFSET = 30
DEFAULT_END_MODE = "sun"
DEFAULT_END_OFFSET = -60
DEFAULT_RAIN_DELAY = 60

_LOGGER = logging.getLogger(__name__)


class GoatyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Goaty config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial device selection step."""
        errors: dict[str, str] = {}
        entity_reg = er.async_get(self.hass)
        mower_entries = [entry for entry in entity_reg.entities.values() if entry.domain == DEVICE_DOMAIN]
        if not mower_entries:
            return self.async_abort(reason="no_mower_entities")

        if user_input is not None:
            entity_id = str(user_input[CONF_MOWER_ENTITY_ID]).strip()
            entity_entry = entity_reg.async_get(entity_id)
            if entity_entry is None:
                errors["base"] = "no_device"
            else:
                device_id = str(entity_entry.device_id or "").strip()
                if not device_id:
                    errors["base"] = "no_device"
                else:
                    device_reg = dr.async_get(self.hass)
                    device_entry = device_reg.async_get(device_id)
                    device_name = self._device_name(entity_id, device_entry)

                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()

                    self._config = {
                        CONF_MOWER_ENTITY_ID: entity_id,
                        CONF_DEVICE_ID: device_id,
                        CONF_DEVICE_NAME: device_name,
                    }
                    return await self.async_step_image()

        default_entity = mower_entries[0].entity_id
        data_schema = vol.Schema(
            {
                vol.Required(CONF_MOWER_ENTITY_ID, default=default_entity): EntitySelector(
                    EntitySelectorConfig(domain=DEVICE_DOMAIN)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_image(self, user_input: dict[str, Any] | None = None):
        """Choose the map image source."""
        if user_input is not None:
            image_source = str(user_input[CONF_IMAGE_SOURCE])
            self._config[CONF_IMAGE_SOURCE] = image_source
            if image_source == "url":
                return await self.async_step_image_url()
            if image_source == "file":
                return await self.async_step_image_file()

            self._config[CONF_IMAGE_PATH] = None
            self._config[CONF_IMAGE_SOURCE_URL] = None
            return await self.async_step_calibration()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_IMAGE_SOURCE, default="file"): vol.In(
                    {
                        "url": "Bild-URL (WMS oder direkter Link)",
                        "file": "Datei in /config/www/ vorhanden",
                        "none": "Kein Luftbild",
                    }
                )
            }
        )
        return self.async_show_form(step_id="image", data_schema=data_schema)

    async def async_step_image_url(self, user_input: dict[str, Any] | None = None):
        """Download a map image from a URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = str(user_input["image_url"]).strip()
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            errors["image_url"] = "http_error"
                        else:
                            content_type = response.headers.get("Content-Type", "")
                            if "image" not in content_type.lower():
                                errors["image_url"] = "not_an_image"
                            else:
                                image_bytes = await response.read()
                                dest = Path(self.hass.config.path("www")) / DEFAULT_IMAGE_FILENAME
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                await self.hass.async_add_executor_job(
                                    dest.write_bytes,
                                    image_bytes,
                                )
                                self._config[CONF_IMAGE_PATH] = DEFAULT_IMAGE_PATH
                                self._config[CONF_IMAGE_SOURCE_URL] = url
                                return await self.async_step_calibration()
            except Exception:  # pragma: no cover - defensive network/file guard
                _LOGGER.exception("Failed to download Goaty map image from %s", url)
                errors["image_url"] = "download_failed"

        data_schema = vol.Schema(
            {
                vol.Required("image_url"): cv.string,
            }
        )
        return self.async_show_form(
            step_id="image_url",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_image_file(self, user_input: dict[str, Any] | None = None):
        """Select an existing local map image file."""
        errors: dict[str, str] = {}

        if user_input is not None:
            filename = Path(str(user_input["image_filename"]).strip()).name
            path = Path(self.hass.config.path("www")) / filename
            if not path.is_file():
                errors["image_filename"] = "file_not_found"
            else:
                self._config[CONF_IMAGE_PATH] = f"/local/{filename}"
                self._config[CONF_IMAGE_SOURCE_URL] = None
                return await self.async_step_calibration()

        data_schema = vol.Schema(
            {
                vol.Required("image_filename", default=DEFAULT_IMAGE_FILENAME): cv.string,
            }
        )
        return self.async_show_form(
            step_id="image_file",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_calibration(self, user_input: dict[str, Any] | None = None):
        """Collect map calibration settings when an image is present."""
        if not self._config.get(CONF_IMAGE_PATH):
            self._config[CONF_CALIBRATION] = None
            return await self.async_step_timewindow()

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                min_lat = float(user_input["min_lat"])
                max_lat = float(user_input["max_lat"])
                min_lon = float(user_input["min_lon"])
                max_lon = float(user_input["max_lon"])
                charger_lat = float(user_input["charger_lat"])
                charger_lon = float(user_input["charger_lon"])
                img_width = int(user_input["img_width"])
                img_height = int(user_input["img_height"])
            except (TypeError, ValueError):
                errors["base"] = "invalid_coordinates"
            else:
                if max_lat == min_lat or max_lon == min_lon:
                    errors["base"] = "invalid_coordinates"
                else:
                    import math

                    lat_m = (max_lat - min_lat) * 111320
                    lon_m = (max_lon - min_lon) * (
                        111320 * math.cos(math.radians(charger_lat))
                    )
                    if lat_m == 0 or lon_m == 0:
                        errors["base"] = "invalid_coordinates"
                    else:
                        px_per_m_x = img_width / lon_m
                        px_per_m_y = img_height / lat_m
                        charger_px_x = (charger_lon - min_lon) / (max_lon - min_lon) * img_width
                        charger_px_y = (max_lat - charger_lat) / (max_lat - min_lat) * img_height

                        self._config[CONF_CALIBRATION] = {
                            "min_lat": min_lat,
                            "max_lat": max_lat,
                            "min_lon": min_lon,
                            "max_lon": max_lon,
                            "charger_lat": charger_lat,
                            "charger_lon": charger_lon,
                            "charger_px_x": round(charger_px_x, 1),
                            "charger_px_y": round(charger_px_y, 1),
                            "px_per_m_x": round(px_per_m_x, 4),
                            "px_per_m_y": round(px_per_m_y, 4),
                            "img_width": img_width,
                            "img_height": img_height,
                        }
                        return await self.async_step_timewindow()

        calibration = self._config.get(CONF_CALIBRATION, {}) or {}
        data_schema = vol.Schema(
            {
                vol.Required("charger_lat", default=str(DEFAULT_CHARGER_LAT)): cv.string,
                vol.Required("charger_lon", default=str(DEFAULT_CHARGER_LON)): cv.string,
                vol.Required("min_lat", default=str(DEFAULT_MIN_LAT)): cv.string,
                vol.Required("max_lat", default=str(DEFAULT_MAX_LAT)): cv.string,
                vol.Required("min_lon", default=str(DEFAULT_MIN_LON)): cv.string,
                vol.Required("max_lon", default=str(DEFAULT_MAX_LON)): cv.string,
                vol.Required("img_width", default=str(DEFAULT_IMG_WIDTH)): cv.string,
                vol.Required("img_height", default=str(DEFAULT_IMG_HEIGHT)): cv.string,
            }
        )
        return self.async_show_form(
            step_id="calibration",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_timewindow(self, user_input: dict[str, Any] | None = None):
        """Collect the mowing time window."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                start_mode = str(user_input["start_mode"])
                start_offset = int(user_input.get("start_offset", DEFAULT_START_OFFSET))
                start_time = str(user_input.get("start_time") or "").strip() or None
                end_mode = str(user_input["end_mode"])
                end_offset = int(user_input.get("end_offset", DEFAULT_END_OFFSET))
                end_time = str(user_input.get("end_time") or "").strip() or None
                rain_delay = int(user_input.get("rain_delay", DEFAULT_RAIN_DELAY))
                rain_sensor = user_input.get("rain_sensor") or None
            except (TypeError, ValueError):
                errors["base"] = "invalid_timewindow"
            else:
                if start_mode not in {"sun", "time"} or end_mode not in {"sun", "time"}:
                    errors["base"] = "invalid_timewindow"
                else:
                    self._config[CONF_TIME_WINDOW] = {
                        "start_mode": start_mode,
                        "start_offset": start_offset,
                        "start_time": start_time,
                        "end_mode": end_mode,
                        "end_offset": end_offset,
                        "end_time": end_time,
                        "rain_delay_minutes": rain_delay,
                        "rain_sensor_entity": rain_sensor,
                    }
                    return await self.async_step_finish()

        time_window = self._config.get(CONF_TIME_WINDOW, {}) or {}
        data_schema = vol.Schema(
            {
                vol.Required("start_mode", default=time_window.get("start_mode", DEFAULT_START_MODE)): vol.In(
                    {"sun": "Relativ zum Sonnenaufgang", "time": "Feste Zeit"}
                ),
                vol.Required("start_offset", default=time_window.get("start_offset", DEFAULT_START_OFFSET)): vol.Coerce(int),
                vol.Required("start_time", default=time_window.get("start_time", "")): cv.string,
                vol.Required("end_mode", default=time_window.get("end_mode", DEFAULT_END_MODE)): vol.In(
                    {"sun": "Relativ zum Sonnenuntergang", "time": "Feste Zeit"}
                ),
                vol.Required("end_offset", default=time_window.get("end_offset", DEFAULT_END_OFFSET)): vol.Coerce(int),
                vol.Required("end_time", default=time_window.get("end_time", "")): cv.string,
                vol.Required("rain_delay", default=time_window.get("rain_delay_minutes", DEFAULT_RAIN_DELAY)): vol.Coerce(int),
                vol.Optional("rain_sensor"): EntitySelector(EntitySelectorConfig(domain="binary_sensor")),
            }
        )
        return self.async_show_form(
            step_id="timewindow",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        """Finalize the config flow."""
        return self.async_create_entry(
            title=str(self._config[CONF_DEVICE_NAME]),
            data=dict(self._config),
        )

    @staticmethod
    def _device_name(entity_id: str, device_entry: Any | None) -> str:
        name_candidates = [
            getattr(device_entry, "name_by_user", None) if device_entry is not None else None,
            getattr(device_entry, "name", None) if device_entry is not None else None,
            entity_id,
        ]
        for name in name_candidates:
            if name:
                return str(name)
        return entity_id


async def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    """Return the options flow handler."""
    from .options_flow import GoatyOptionsFlowHandler

    return GoatyOptionsFlowHandler(config_entry)
