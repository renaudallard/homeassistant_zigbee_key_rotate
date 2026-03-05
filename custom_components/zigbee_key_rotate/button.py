# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Button entities for Zigbee Key Rotate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import _get_zigpy_app
from .analyze import analyze_network
from .const import SIGNAL_ANALYSIS_UPDATED, SIGNAL_KEY_INFO_UPDATED
from .entity import ZigbeeKeyRotateEntity
from .rotate import get_network_key_info, rotate_network_key

if TYPE_CHECKING:
    from . import ZigbeeKeyRotateConfigEntry, ZigbeeKeyRotateData

_LOGGER = logging.getLogger(__name__)

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="analyze_network",
        translation_key="analyze_network",
        icon="mdi:magnify-scan",
    ),
    ButtonEntityDescription(
        key="rotate_network_key",
        translation_key="rotate_network_key",
        icon="mdi:key-change",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZigbeeKeyRotateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    async_add_entities(
        ZigbeeKeyRotateButton(entry.entry_id, entry.runtime_data, description)
        for description in BUTTON_DESCRIPTIONS
    )


class ZigbeeKeyRotateButton(ZigbeeKeyRotateEntity, ButtonEntity):
    """Button entity for Zigbee Key Rotate."""

    def __init__(
        self,
        entry_id: str,
        data: ZigbeeKeyRotateData,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry_id, data)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._running = False

    async def async_press(self) -> None:
        """Handle button press."""
        if self._running:
            raise HomeAssistantError("Operation already in progress")

        self._running = True
        try:
            if self.entity_description.key == "analyze_network":
                await self._analyze()
            elif self.entity_description.key == "rotate_network_key":
                await self._rotate()
        finally:
            self._running = False

    async def _analyze(self) -> None:
        """Run network analysis."""
        app = _get_zigpy_app(self.hass)
        result = analyze_network(app)
        self._data.analysis = result
        async_dispatcher_send(self.hass, f"{SIGNAL_ANALYSIS_UPDATED}_{self._entry_id}")

    async def _rotate(self) -> None:
        """Run key rotation."""
        app = _get_zigpy_app(self.hass)
        broadcast_count = int(self._data.number_values["broadcast_count"])
        switch_delay = self._data.number_values["switch_delay"]

        try:
            await rotate_network_key(
                app,
                broadcast_count=broadcast_count,
                switch_delay=switch_delay,
            )
        except Exception as err:
            _LOGGER.exception("Network key rotation failed")
            raise HomeAssistantError(f"Key rotation failed: {err}") from err

        self._data.key_info = get_network_key_info(app)
        async_dispatcher_send(self.hass, f"{SIGNAL_KEY_INFO_UPDATED}_{self._entry_id}")
