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

"""Number entities for Zigbee Key Rotate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_BROADCAST_COUNT, DEFAULT_SWITCH_DELAY
from .entity import ZigbeeKeyRotateEntity

if TYPE_CHECKING:
    from . import ZigbeeKeyRotateConfigEntry, ZigbeeKeyRotateData


@dataclass(frozen=True, kw_only=True)
class ZigbeeKeyRotateNumberDescription(NumberEntityDescription):
    """Number entity description with a default value."""

    default_value: float


NUMBER_DESCRIPTIONS: tuple[ZigbeeKeyRotateNumberDescription, ...] = (
    ZigbeeKeyRotateNumberDescription(
        key="broadcast_count",
        translation_key="broadcast_count",
        icon="mdi:broadcast",
        native_min_value=1,
        native_max_value=20,
        native_step=1,
        default_value=DEFAULT_BROADCAST_COUNT,
        entity_category=EntityCategory.CONFIG,
    ),
    ZigbeeKeyRotateNumberDescription(
        key="switch_delay",
        translation_key="switch_delay",
        icon="mdi:timer-sand",
        native_min_value=5,
        native_max_value=300,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        default_value=DEFAULT_SWITCH_DELAY,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZigbeeKeyRotateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    async_add_entities(
        ZigbeeKeyRotateNumber(entry.entry_id, entry.runtime_data, description)
        for description in NUMBER_DESCRIPTIONS
    )


class ZigbeeKeyRotateNumber(ZigbeeKeyRotateEntity, NumberEntity):
    """Number entity for Zigbee Key Rotate."""

    entity_description: ZigbeeKeyRotateNumberDescription

    def __init__(
        self,
        entry_id: str,
        data: ZigbeeKeyRotateData,
        description: ZigbeeKeyRotateNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(entry_id, data)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def native_value(self) -> float:
        """Return the current value from runtime data."""
        return self._data.number_values[self.entity_description.key]

    async def async_set_native_value(self, value: float) -> None:
        """Update the value in runtime data."""
        self._data.number_values[self.entity_description.key] = value
        self.async_write_ha_state()
