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

"""Sensor entities for Zigbee Key Rotate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import SIGNAL_ANALYSIS_UPDATED, SIGNAL_KEY_INFO_UPDATED
from .entity import ZigbeeKeyRotateEntity

if TYPE_CHECKING:
    from . import ZigbeeKeyRotateConfigEntry, ZigbeeKeyRotateData


@dataclass(frozen=True, kw_only=True)
class ZigbeeKeyRotateSensorDescription(SensorEntityDescription):
    """Sensor entity description with value and attribute callables."""

    value_fn: Callable[[dict[str, Any] | None], StateType]
    attr_fn: Callable[[dict[str, Any] | None], dict[str, Any] | None] | None = None
    signal: str
    data_key: str


SENSOR_DESCRIPTIONS: tuple[ZigbeeKeyRotateSensorDescription, ...] = (
    ZigbeeKeyRotateSensorDescription(
        key="network_key",
        translation_key="network_key",
        icon="mdi:key-variant",
        signal=SIGNAL_KEY_INFO_UPDATED,
        data_key="key_info",
        value_fn=lambda d: f"\u00b7\u00b7\u00b7\u00b7{d['network_key'][-4:]}"
        if d
        else None,
        attr_fn=lambda d: {"full_key": d["network_key"]} if d else None,
    ),
    ZigbeeKeyRotateSensorDescription(
        key="key_sequence",
        translation_key="key_sequence",
        icon="mdi:counter",
        signal=SIGNAL_KEY_INFO_UPDATED,
        data_key="key_info",
        value_fn=lambda d: d["key_sequence"] if d else None,
    ),
    ZigbeeKeyRotateSensorDescription(
        key="radio_type",
        translation_key="radio_type",
        icon="mdi:radio-tower",
        signal=SIGNAL_KEY_INFO_UPDATED,
        data_key="key_info",
        value_fn=lambda d: d["radio_type"] if d else None,
    ),
    ZigbeeKeyRotateSensorDescription(
        key="channel",
        translation_key="channel",
        icon="mdi:sine-wave",
        signal=SIGNAL_KEY_INFO_UPDATED,
        data_key="key_info",
        value_fn=lambda d: d["channel"] if d else None,
    ),
    ZigbeeKeyRotateSensorDescription(
        key="pan_id",
        translation_key="pan_id",
        icon="mdi:identifier",
        signal=SIGNAL_KEY_INFO_UPDATED,
        data_key="key_info",
        value_fn=lambda d: d["pan_id"] if d else None,
    ),
    ZigbeeKeyRotateSensorDescription(
        key="network_readiness",
        translation_key="network_readiness",
        icon="mdi:check-network",
        signal=SIGNAL_ANALYSIS_UPDATED,
        data_key="analysis",
        value_fn=lambda d: (
            "Ready"
            if d and d["summary"]["ready_for_rotation"]
            else ("Not ready" if d else None)
        ),
        attr_fn=lambda d: (
            {
                "recommendation": d["summary"]["recommendation"],
                "total_devices": d["summary"]["total_devices"],
            }
            if d
            else None
        ),
    ),
    ZigbeeKeyRotateSensorDescription(
        key="devices_at_risk",
        translation_key="devices_at_risk",
        icon="mdi:alert-circle-outline",
        signal=SIGNAL_ANALYSIS_UPDATED,
        data_key="analysis",
        value_fn=lambda d: (
            f"{d['summary']['risk_breakdown']['critical']} critical, "
            f"{d['summary']['risk_breakdown']['high']} high, "
            f"{d['summary']['risk_breakdown']['medium']} medium, "
            f"{d['summary']['risk_breakdown']['low']} low"
        )
        if d
        else None,
        attr_fn=lambda d: (
            {
                "risk_breakdown": d["summary"]["risk_breakdown"],
                **{
                    f"{level}_devices": [
                        f"{dev['manufacturer']} {dev['model']} ({dev['ieee']})"
                        for dev in d["devices"]
                        if dev["rotation_risk"] == level
                    ]
                    for level in ("critical", "high", "medium")
                    if any(dev["rotation_risk"] == level for dev in d["devices"])
                },
            }
            if d
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZigbeeKeyRotateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    async_add_entities(
        ZigbeeKeyRotateSensor(entry.entry_id, entry.runtime_data, description)
        for description in SENSOR_DESCRIPTIONS
    )


class ZigbeeKeyRotateSensor(ZigbeeKeyRotateEntity, SensorEntity):
    """Sensor entity for Zigbee Key Rotate."""

    entity_description: ZigbeeKeyRotateSensorDescription

    def __init__(
        self,
        entry_id: str,
        data: ZigbeeKeyRotateData,
        description: ZigbeeKeyRotateSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry_id, data)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the sensor value from runtime data."""
        data = getattr(self._data, self.entity_description.data_key)
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.attr_fn is None:
            return None
        data = getattr(self._data, self.entity_description.data_key)
        return self.entity_description.attr_fn(data)

    async def async_added_to_hass(self) -> None:
        """Register dispatcher signal listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self.entity_description.signal}_{self._entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle data update signal."""
        self.async_write_ha_state()
