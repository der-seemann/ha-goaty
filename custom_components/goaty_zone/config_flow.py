"""Config flow for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from . import DOMAIN

CONF_MOWER_ENTITY_ID = "mower_entity_id"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
DEVICE_DOMAIN = "lawn_mower"


class GoatyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Goaty config flow."""

    VERSION = 1

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

                    return self.async_create_entry(
                        title=device_name,
                        data={
                            CONF_MOWER_ENTITY_ID: entity_id,
                            CONF_DEVICE_ID: device_id,
                            CONF_DEVICE_NAME: device_name,
                        },
                    )

        default_entity = mower_entries[0].entity_id
        data_schema = vol.Schema(
            {
                vol.Required(CONF_MOWER_ENTITY_ID, default=default_entity): EntitySelector(
                    EntitySelectorConfig(domain=DEVICE_DOMAIN)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

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
