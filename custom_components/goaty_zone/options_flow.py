"""Options flow for Goaty Zone Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries


class GoatyOptionsFlowHandler(config_entries.OptionsFlow):
    """Placeholder options flow for the phased refactor."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show a minimal placeholder form."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
