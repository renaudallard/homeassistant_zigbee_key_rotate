# Zigbee Network Key Rotation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.2+-blue)](https://www.home-assistant.io)
[![License: BSD-2-Clause](https://img.shields.io/badge/License-BSD--2--Clause-blue.svg)](LICENSE)

A Home Assistant custom integration that rotates Zigbee network encryption keys **without re-pairing devices**.

Includes a pre-rotation device analyzer that checks every device on your network for Zigbee 3.0 compliance issues before you rotate.

---

## Table of contents

- [How it works](#how-it-works)
- [Supported radios](#supported-radios)
- [Requirements](#requirements)
- [Installation](#installation)
- [Device page](#device-page)
  - [Sensors](#sensors)
  - [Buttons](#buttons)
  - [Configuration](#configuration)
- [Usage](#usage)
  - [Step 1: Analyze your network](#step-1-analyze-your-network)
  - [Step 2: Rotate the key](#step-2-rotate-the-key)
  - [Step 3: Verify](#step-3-verify)
- [Services reference](#services-reference)
  - [analyze_devices](#zigbee_key_rotateanalyze_devices)
  - [rotate_network_key](#zigbee_key_rotaterotate_network_key)
  - [get_network_key_info](#zigbee_key_rotateget_network_key_info)
- [Device compatibility](#device-compatibility)
- [Troubleshooting](#troubleshooting)

---

## How it works

Zigbee networks use a shared 128-bit network key to encrypt all traffic. This integration implements the standard **Zigbee Trust Center key update** procedure defined in the Zigbee 3.0 specification:

```
Coordinator                          All devices
     |                                    |
     |  Phase 1: Transport Key            |
     |----------------------------------->|  New key encrypted with old key
     |        (repeated N times)          |  Devices store it as "next key"
     |                                    |
     |  ... wait for propagation ...      |
     |                                    |
     |  Phase 2: Switch Key               |
     |----------------------------------->|  All devices activate the new key
     |                                    |
```

1. **Phase 1 (Key Distribution)** . The coordinator broadcasts the new network key to all devices, encrypted with the current key. Sent multiple times to maximize delivery.
2. **Propagation delay** . A configurable wait gives all devices time to receive the new key. Battery-powered sleepy devices only communicate when they wake up, so this delay matters.
3. **Phase 2 (Key Switch)** . The coordinator broadcasts a switch command. Every device that received the new key activates it immediately.

Backups of the network state are created automatically before and after each rotation.

---

## Supported radios

| Radio | Chipset | Protocol | Status |
|:------|:--------|:---------|:------:|
| Silicon Labs (EZSP) | EFR32, EM35x | `broadcastNextNetworkKey` / `broadcastNetworkKeySwitch` | Supported |
| Texas Instruments (ZNP) | CC2652, CC2531, CC1352 | `ZDO.ExtUpdateNwkKey` / `ZDO.ExtSwitchNwkKey` | Supported |
| deCONZ | ConBee, RaspBee | | Not supported |
| ZiGate | | | Not supported |

---

## Requirements

- Home Assistant **2026.2** or newer
- **ZHA** integration configured and running
- A supported Zigbee radio adapter

---

## Installation

### HACS (recommended)

1. In HACS, go to **Integrations** and click the three-dot menu.
2. Select **Custom repositories**.
3. Paste `https://github.com/renaudallard/homeassistant_zigbee_key_rotate` and select category **Integration**.
4. Click **Add**.
5. Search for **Zigbee Network Key Rotation** in the HACS integrations list and click **Download**.
6. Restart Home Assistant.
7. Go to **Settings > Devices & Services > Add Integration** and search for "Zigbee Network Key Rotation".

### Manual

1. Copy the `custom_components/zigbee_key_rotate` folder into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration** and search for "Zigbee Network Key Rotation".

---

## Device page

After installation, the integration creates a **Zigbee Network Key Rotation** device under **Settings > Devices & Services**. The device page provides sensors, buttons, and configuration numbers so you can monitor and operate key rotation directly from the UI without calling services manually.

### Sensors

| Entity | Description |
|:-------|:------------|
| **Network key** | Current network key (masked). The full key is available in the `full_key` attribute. |
| **Key sequence** | Current key sequence number. |
| **Radio type** | Detected radio type (`ezsp` or `znp`). |
| **Channel** | Zigbee network channel. |
| **PAN ID** | Network PAN ID (hex). |
| **Network readiness** | `Ready` or `Not ready` based on the last analysis. Shows `Unknown` until you press the Analyze button. |
| **Devices at risk** | Summary of devices by risk level (e.g. `0 critical, 2 high, 4 medium`). Shows `Unknown` until you press the Analyze button. |

The first five sensors populate automatically at startup. The last two require pressing the **Analyze network** button first.

### Buttons

| Entity | Description |
|:-------|:------------|
| **Analyze network** | Runs the device compliance analyzer and updates the readiness and risk sensors. |
| **Rotate network key** | Performs the two-phase key rotation using the current broadcast count and switch delay values. Updates all key info sensors afterward. |

Both buttons guard against concurrent presses.

### Configuration

| Entity | Range | Default | Description |
|:-------|:------|:--------|:------------|
| **Broadcast count** | 1 .. 20 | 5 | Number of times to broadcast the new key before switching. |
| **Switch delay** | 5 .. 300 s | 300 | Seconds to wait between key distribution and the switch command. |

These values are used by the **Rotate network key** button. They reset to defaults on HA restart.

---

## Usage

### Step 1: Analyze your network

Before rotating, run the analyzer to check every device for potential issues:

```yaml
service: zigbee_key_rotate.analyze_devices
```

The response includes a per-device risk assessment and a network summary:

```json
{
  "summary": {
    "total_devices": 23,
    "risk_breakdown": { "low": 18, "medium": 4, "high": 0, "critical": 1 },
    "ready_for_rotation": false,
    "recommendation": "1 device(s) have critical issues..."
  },
  "devices": [
    {
      "ieee": "00:15:8d:00:04:ab:cd:ef",
      "manufacturer": "LUMI",
      "model": "lumi.sensor_motion.aq2",
      "device_type": "end_device",
      "is_security_capable": true,
      "rotation_risk": "medium",
      "issues": [
        {
          "severity": "warning",
          "category": "key_rotation",
          "message": "Sleepy end device (RxOnWhenIdle=false)..."
        }
      ]
    }
  ]
}
```

Review any devices with `critical` or `high` risk. These devices may need re-pairing after rotation.

### Step 2: Rotate the key

Once satisfied with the analysis, rotate the key:

```yaml
service: zigbee_key_rotate.rotate_network_key
data:
  broadcast_count: 10
  switch_delay: 60
```

A random 128-bit key is generated automatically. The service logs each phase to the Home Assistant log.

### Step 3: Verify

Check that the key has changed:

```yaml
service: zigbee_key_rotate.get_network_key_info
```

Monitor your devices over the next few minutes. Battery-powered devices may take a few wake cycles to start communicating with the new key.

---

## Services reference

### `zigbee_key_rotate.analyze_devices`

Analyze Zigbee devices for Zigbee 3.0 compliance and key rotation readiness. Returns structured data. Must be called with **response data**.

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `ieee` | string | *(all devices)* | Analyze a single device by IEEE address (e.g. `00:11:22:33:44:55:66:77`). Omit to analyze the full network. |

**Risk levels:**

| Risk | Meaning |
|:-----|:--------|
| `low` | Fully Zigbee 3.0 compliant. Key rotation should work. |
| `medium` | Minor concerns: sleepy device, weak signal, old stack version. Should work but monitor closely. |
| `high` | Device is offline or has multiple issues. May require re-pairing after rotation. |
| `critical` | Device does not support security or was never fully interviewed. Will almost certainly fail. |

**Checks performed per device:**

| Check | What it looks at |
|:------|:-----------------|
| Node descriptor | Security capability flag, device type (router/end device), FFD status |
| MAC capabilities | RxOnWhenIdle (sleepy vs always-on), power source |
| Endpoint profiles | Home Automation (0x0104) vs ZigBee Light Link (0xC05E) vs unknown |
| Basic cluster cache | ZCL version, stack version |
| Signal quality | LQI and RSSI values |
| Availability | Time since last communication (>24h = critical) |
| Manufacturer | Known non-standard implementations (Xiaomi/Aqara/LUMI) |
| Trust Center link key | Whether the device has a dedicated link key |

---

### `zigbee_key_rotate.rotate_network_key`

Perform the two-phase key rotation. Supports **response data** (returns old key, new key, status).

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `new_key` | string | *(random)* | 32-character hex string for the new key. A cryptographically random key is generated if omitted. |
| `broadcast_count` | int | `5` | Number of times to broadcast the new key before switching (1 .. 20). |
| `switch_delay` | int | `300` | Seconds to wait between key distribution and the switch command (5 .. 300). |

**Example with a specific key:**

```yaml
service: zigbee_key_rotate.rotate_network_key
data:
  new_key: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  broadcast_count: 10
  switch_delay: 120
```

**Recommended `switch_delay` values:**

| Network type | Delay |
|:-------------|:------|
| Mains-powered devices only | 10 - 30s |
| Mixed (mains + battery) | 60 - 120s |
| Many sleepy end devices | 120 - 300s |

---

### `zigbee_key_rotate.get_network_key_info`

Return current Zigbee network key information. Must be called with **response data**.

```yaml
service: zigbee_key_rotate.get_network_key_info
```

**Response:**

```json
{
  "network_key": "01020304050607080910111213141516",
  "key_sequence": 0,
  "key_tx_counter": 12345,
  "pan_id": "0x1A2B",
  "extended_pan_id": "ab:cd:ef:01:02:03:04:05",
  "channel": 15,
  "nwk_update_id": 0,
  "radio_type": "ezsp"
}
```

---

## Device compatibility

### Zigbee 3.0 devices

All devices certified under the Zigbee 3.0 specification are required to support Trust Center key updates. These should rotate without issues.

### Pre-Zigbee 3.0 devices

Older devices (Zigbee HA 1.2, ZLL) may or may not handle key rotation correctly. The `analyze_devices` service will flag these based on their reported ZCL and stack versions.

### Known problematic devices

| Manufacturer | Notes |
|:-------------|:------|
| Xiaomi / Aqara / LUMI | Documented to use non-standard join and rejoin mechanisms. High risk of dropping off the network after key rotation. Plan to re-pair these devices. |

The analyzer flags these automatically. If you have many such devices, consider whether rotation is worth the effort, or plan for re-pairing them afterward.

---

## Troubleshooting

### Devices unresponsive after rotation

1. **Wait a few minutes.** Battery-powered devices need to wake up and poll their parent router before receiving the new key.
2. **Check Home Assistant logs.** Look for `zigbee_key_rotate` log entries showing the status of each phase.
3. **Power-cycle mains-powered devices** that are not responding.
4. **Re-pair affected devices** from ZHA if they do not recover.

### Entire network broken

1. Go to **ZHA > Configure > Network Settings**.
2. Restore the **pre-rotation backup** that was automatically created.
3. All devices should resume communication with the old key.

### All broadcasts failed

If the rotation service returns an error about all broadcasts failing, the key was **not** switched. Your network is still on the old key and no action is needed. Check the coordinator connection and try again.

### Coordinator not supported

Only Silicon Labs (EZSP) and Texas Instruments (ZNP) based coordinators are supported. deCONZ and ZiGate do not expose the necessary Trust Center key update commands.

---

## Technical details

### EZSP (Silicon Labs)

Uses EZSP frame 0x73 `broadcastNextNetworkKey(key)` to distribute the new key encrypted with the current network key, followed by frame 0x74 `broadcastNetworkKeySwitch()` to trigger the switch. These commands are defined in EZSPv4 and inherited through all subsequent protocol versions.

### ZNP (Texas Instruments)

Uses Z-Stack ZDO extension commands `ExtUpdateNwkKey(Dst, KeySeqNum, Key)` to distribute the new key with an incremented sequence number, followed by `ExtSwitchNwkKey(Dst, KeySeqNum)` to trigger the switch. Both commands broadcast to address 0xFFFF (all devices).

### Backup safety

A full network backup (zigpy open coordinator backup format) is created before rotation begins. If the pre-rotation backup fails, the rotation is aborted. A post-rotation backup is attempted but its failure does not affect the rotation result.

---

## License

BSD 2-Clause
