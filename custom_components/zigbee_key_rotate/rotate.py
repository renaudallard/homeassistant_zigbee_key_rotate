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

"""Core Zigbee network key rotation logic."""

import asyncio
import logging
import secrets
from typing import Any

from zigpy.types import KeyData

_LOGGER = logging.getLogger(__name__)


def generate_network_key() -> bytes:
    """Generate a cryptographically random 128-bit network key."""
    return secrets.token_bytes(16)


def parse_key_hex(key_hex: str) -> bytes:
    """Parse a hex string into a 16-byte key."""
    key_hex = key_hex.replace(":", "").replace(" ", "").replace("-", "")
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 16:
        raise ValueError(f"Key must be exactly 16 bytes, got {len(key_bytes)}")
    return key_bytes


def detect_radio_type(app: Any) -> str:
    """Detect the radio type from the application controller."""
    if hasattr(app, "_ezsp"):
        return "ezsp"
    if hasattr(app, "_znp"):
        return "znp"
    return "unknown"


async def rotate_key_ezsp(
    app: Any,
    new_key_bytes: bytes,
    broadcast_count: int,
    switch_delay: float,
) -> dict[str, Any]:
    """Rotate network key using EZSP (Silicon Labs) radio.

    Phase 1: Broadcast the new network key encrypted with the current key.
    Phase 2: After a delay, broadcast the switch command to activate it.
    """
    ezsp = app._ezsp
    key_data = KeyData(new_key_bytes)

    _LOGGER.info(
        "EZSP: Phase 1. Broadcasting new network key (%d times)", broadcast_count
    )
    success_count = 0
    for i in range(broadcast_count):
        result = await ezsp.broadcastNextNetworkKey(key_data)
        status = result[0]
        _LOGGER.debug(
            "EZSP: Broadcast %d/%d status: %s", i + 1, broadcast_count, status
        )
        if status == 0:
            success_count += 1
        if i < broadcast_count - 1:
            await asyncio.sleep(1.0)

    if success_count == 0:
        raise RuntimeError(
            f"All {broadcast_count} key broadcast attempts failed. "
            f"Last status: {status}. Aborting key switch."
        )

    _LOGGER.info(
        "EZSP: Waiting %d seconds for key propagation to all devices", switch_delay
    )
    await asyncio.sleep(switch_delay)

    _LOGGER.info("EZSP: Phase 2. Broadcasting key switch command")
    result = await ezsp.broadcastNetworkKeySwitch()
    status = result[0]
    _LOGGER.info("EZSP: Key switch status: %s", status)

    return {"radio": "ezsp", "switch_status": str(status)}


async def rotate_key_znp(
    app: Any,
    new_key_bytes: bytes,
    broadcast_count: int,
    switch_delay: float,
) -> dict[str, Any]:
    """Rotate network key using ZNP (Texas Instruments) radio.

    Uses ZDO.ExtUpdateNwkKey and ZDO.ExtSwitchNwkKey commands.
    """
    import zigpy_znp.commands as c

    znp = app._znp

    current_seq = app.state.network_info.network_key.seq
    next_seq = (current_seq + 1) % 256

    # 0xFFFF = broadcast to all devices
    broadcast_addr = 0xFFFF

    _LOGGER.info(
        "ZNP: Phase 1. Broadcasting new network key (seq %d -> %d, %d times)",
        current_seq,
        next_seq,
        broadcast_count,
    )
    success_count = 0
    for i in range(broadcast_count):
        result = await znp.request(
            c.ZDO.ExtUpdateNwkKey.Req(
                Dst=broadcast_addr,
                KeySeqNum=next_seq,
                Key=KeyData(new_key_bytes),
            )
        )
        status = result.Status
        _LOGGER.debug("ZNP: Broadcast %d/%d status: %s", i + 1, broadcast_count, status)
        if status == 0:
            success_count += 1
        if i < broadcast_count - 1:
            await asyncio.sleep(1.0)

    if success_count == 0:
        raise RuntimeError(
            f"All {broadcast_count} key broadcast attempts failed. "
            f"Last status: {status}. Aborting key switch."
        )

    _LOGGER.info(
        "ZNP: Waiting %d seconds for key propagation to all devices", switch_delay
    )
    await asyncio.sleep(switch_delay)

    _LOGGER.info("ZNP: Phase 2. Broadcasting key switch command")
    result = await znp.request(
        c.ZDO.ExtSwitchNwkKey.Req(
            Dst=broadcast_addr,
            KeySeqNum=next_seq,
        )
    )
    _LOGGER.info("ZNP: Key switch status: %s", result)

    return {"radio": "znp", "new_key_seq": next_seq, "switch_status": str(result)}


async def rotate_network_key(
    app: Any,
    new_key: bytes | None = None,
    broadcast_count: int = 5,
    switch_delay: float = 30,
) -> dict[str, Any]:
    """Rotate the Zigbee network key.

    1. Creates a backup of the current network state.
    2. Generates or validates the new key.
    3. Broadcasts the new key to all devices (Phase 1).
    4. Waits for propagation.
    5. Sends the switch command (Phase 2).
    6. Reloads local network info.
    7. Creates a new backup.

    Returns a dict with operation details.
    """
    if new_key is None:
        new_key = generate_network_key()

    old_key_hex = app.state.network_info.network_key.key.serialize().hex()
    new_key_hex = new_key.hex()
    _LOGGER.info("Starting network key rotation")
    _LOGGER.debug("Old key: %s", old_key_hex)
    _LOGGER.debug("New key: %s", new_key_hex)

    # Create backup before rotation
    _LOGGER.info("Creating pre-rotation backup")
    await app.backups.create_backup()

    radio = detect_radio_type(app)

    if radio == "ezsp":
        result = await rotate_key_ezsp(app, new_key, broadcast_count, switch_delay)
    elif radio == "znp":
        result = await rotate_key_znp(app, new_key, broadcast_count, switch_delay)
    else:
        raise ValueError(
            f"Unsupported radio type. "
            f"Only Silicon Labs (EZSP) and Texas Instruments (ZNP) are supported. "
            f"Detected controller: {type(app).__module__}.{type(app).__name__}"
        )

    # Reload network info from the radio to reflect the new key
    _LOGGER.info("Reloading network info from coordinator")
    await app.load_network_info()

    new_key_after = app.state.network_info.network_key.key.serialize().hex()
    _LOGGER.info("Network key after rotation: %s", new_key_after)

    # Create post-rotation backup (non-fatal since rotation already succeeded)
    try:
        _LOGGER.info("Creating post-rotation backup")
        await app.backups.create_backup()
    except Exception:
        _LOGGER.warning("Failed to create post-rotation backup", exc_info=True)

    result["old_key"] = old_key_hex
    result["new_key"] = new_key_hex
    result["verified_key"] = new_key_after
    return result


def get_network_key_info(app: Any) -> dict[str, Any]:
    """Return current network key information."""
    ni = app.state.network_info
    key = ni.network_key

    return {
        "network_key": key.key.serialize().hex(),
        "key_sequence": key.seq,
        "key_tx_counter": key.tx_counter,
        "pan_id": f"0x{ni.pan_id:04X}",
        "extended_pan_id": str(ni.extended_pan_id),
        "channel": ni.channel,
        "nwk_update_id": ni.nwk_update_id,
        "radio_type": detect_radio_type(app),
    }
