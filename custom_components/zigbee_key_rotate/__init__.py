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

"""Zigbee Network Key Rotation integration for Home Assistant."""

import logging
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .analyze import analyze_network, analyze_single_device
from .const import (
    DEFAULT_BROADCAST_COUNT,
    DEFAULT_SWITCH_DELAY,
    DOMAIN,
    SERVICE_ANALYZE,
    SERVICE_GET_KEY_INFO,
    SERVICE_ROTATE_KEY,
)
from .helpers import enrich_with_device_names, get_zigpy_app
from .rotate import get_network_key_info, parse_key_hex, rotate_network_key


@dataclass
class ZigbeeKeyRotateData:
    """Runtime data for the Zigbee Key Rotate integration."""

    key_info: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    number_values: dict[str, float] = field(
        default_factory=lambda: {
            "broadcast_count": float(DEFAULT_BROADCAST_COUNT),
            "switch_delay": float(DEFAULT_SWITCH_DELAY),
        }
    )


type ZigbeeKeyRotateConfigEntry = ConfigEntry[ZigbeeKeyRotateData]

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER]

_LOGGER = logging.getLogger(__name__)

ROTATE_KEY_SCHEMA = vol.Schema(
    {
        vol.Optional("new_key"): str,
        vol.Optional("broadcast_count", default=DEFAULT_BROADCAST_COUNT): vol.All(
            int, vol.Range(min=1, max=20)
        ),
        vol.Optional("switch_delay", default=DEFAULT_SWITCH_DELAY): vol.All(
            vol.Coerce(float), vol.Range(min=5, max=300)
        ),
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZigbeeKeyRotateConfigEntry
) -> bool:
    """Set up Zigbee Key Rotate from a config entry."""
    data = ZigbeeKeyRotateData()
    entry.runtime_data = data

    try:
        app = get_zigpy_app(hass)
        data.key_info = get_network_key_info(app)
    except HomeAssistantError:
        _LOGGER.warning("Could not fetch initial key info. ZHA may not be ready yet.")

    async def handle_rotate_key(call: ServiceCall) -> dict:
        """Handle the rotate_network_key service call."""
        app = get_zigpy_app(hass)

        new_key = None
        if "new_key" in call.data and call.data["new_key"]:
            try:
                new_key = parse_key_hex(call.data["new_key"])
            except (ValueError, TypeError) as err:
                raise HomeAssistantError(
                    f"Invalid key format: {err}. "
                    f"Provide a 32-character hex string (16 bytes)."
                ) from err

        broadcast_count = call.data.get("broadcast_count", DEFAULT_BROADCAST_COUNT)
        switch_delay = call.data.get("switch_delay", DEFAULT_SWITCH_DELAY)

        try:
            result = await rotate_network_key(
                app,
                new_key=new_key,
                broadcast_count=broadcast_count,
                switch_delay=switch_delay,
            )
        except Exception as err:
            _LOGGER.exception("Network key rotation failed")
            raise HomeAssistantError(f"Key rotation failed: {err}") from err

        _LOGGER.info("Network key rotation completed: %s", result)
        return result

    async def handle_get_key_info(call: ServiceCall) -> dict:
        """Handle the get_network_key_info service call."""
        app = get_zigpy_app(hass)
        return get_network_key_info(app)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ROTATE_KEY,
        handle_rotate_key,
        schema=ROTATE_KEY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_KEY_INFO,
        handle_get_key_info,
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_analyze(call: ServiceCall) -> dict:
        """Handle the analyze_devices service call."""
        app = get_zigpy_app(hass)

        ieee = call.data.get("ieee")
        if ieee:
            from zigpy.types import EUI64

            try:
                target_ieee = EUI64.convert(ieee)
            except (ValueError, TypeError) as err:
                raise HomeAssistantError(f"Invalid IEEE address: {ieee}") from err

            device = app.devices.get(target_ieee)
            if device is None:
                raise HomeAssistantError(f"Device {ieee} not found on the network")

            key_table = getattr(app.state.network_info, "key_table", [])
            return analyze_single_device(device, key_table)

        result = analyze_network(app)
        enrich_with_device_names(hass, result)
        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_ANALYZE,
        handle_analyze,
        schema=vol.Schema({vol.Optional("ieee"): str}),
        supports_response=SupportsResponse.ONLY,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ZigbeeKeyRotateConfigEntry
) -> bool:
    """Unload a config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_ROTATE_KEY)
    hass.services.async_remove(DOMAIN, SERVICE_GET_KEY_INFO)
    hass.services.async_remove(DOMAIN, SERVICE_ANALYZE)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
