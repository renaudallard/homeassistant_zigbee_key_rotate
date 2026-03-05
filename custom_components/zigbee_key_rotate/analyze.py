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

"""Zigbee 3.0 compliance analysis for key rotation readiness."""

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Profile IDs
PROFILE_HA = 0x0104  # Home Automation (ZB3 primary)
PROFILE_ZLL = 0xC05E  # ZigBee Light Link (pre-ZB3, merged into ZB3)
PROFILE_SE = 0x0109  # Smart Energy
PROFILE_GP = 0xA1E0  # Green Power

PROFILE_NAMES = {
    PROFILE_HA: "Home Automation",
    PROFILE_ZLL: "ZigBee Light Link",
    PROFILE_SE: "Smart Energy",
    PROFILE_GP: "Green Power",
}

# Basic cluster ID
CLUSTER_BASIC = 0x0000

# Manufacturers with documented non-standard Zigbee behavior
KNOWN_QUIRKY_MANUFACTURERS = {
    "LUMI": (
        "Xiaomi/Aqara devices are documented to use non-standard join and "
        "rejoin mechanisms. They may drop off the network after key rotation "
        "and require re-pairing."
    ),
    "Xiaomi": (
        "Xiaomi devices are documented to use non-standard join and "
        "rejoin mechanisms. They may drop off the network after key rotation "
        "and require re-pairing."
    ),
}

# Unavailability threshold: device not seen for more than 24 hours
UNAVAILABLE_THRESHOLD_S = 86400


def _check_node_descriptor(device: Any) -> list[dict[str, str]]:
    """Check node descriptor for compliance issues."""
    issues = []

    if device.node_desc is None:
        issues.append(
            {
                "severity": "critical",
                "category": "protocol",
                "message": (
                    "No node descriptor available. Device was not fully interviewed. "
                    "It cannot be verified for compliance and may not receive key updates."
                ),
            }
        )
        return issues

    nd = device.node_desc

    if not nd.is_security_capable:
        issues.append(
            {
                "severity": "critical",
                "category": "security",
                "message": (
                    "Device does not advertise security capability in its node descriptor. "
                    "Zigbee 3.0 requires all devices to support APS-layer security. "
                    "This device will likely fail to process a network key update."
                ),
            }
        )

    if nd.is_end_device and not nd.is_receiver_on_when_idle:
        issues.append(
            {
                "severity": "warning",
                "category": "key_rotation",
                "message": (
                    "Sleepy end device (RxOnWhenIdle=false). This device only "
                    "communicates when it wakes up to poll its parent. It may miss "
                    "the new key broadcast and require a longer switch_delay or re-pairing."
                ),
            }
        )

    if nd.is_end_device:
        issues.append(
            {
                "severity": "info",
                "category": "protocol",
                "message": (
                    "End device. It receives the network key from its parent router, "
                    "not directly from the coordinator broadcast."
                ),
            }
        )

    if nd.is_router and not nd.is_full_function_device:
        issues.append(
            {
                "severity": "warning",
                "category": "protocol",
                "message": (
                    "Router that is not a Full Function Device (FFD). "
                    "Zigbee 3.0 requires routers to be FFDs."
                ),
            }
        )

    return issues


def _check_endpoints(device: Any) -> list[dict[str, str]]:
    """Check endpoint profiles and clusters for compliance."""
    issues = []

    non_zdo_endpoints = {eid: ep for eid, ep in device.endpoints.items() if eid != 0}

    if not non_zdo_endpoints:
        issues.append(
            {
                "severity": "warning",
                "category": "protocol",
                "message": "No application endpoints found (only ZDO).",
            }
        )
        return issues

    profile_ids = set()
    has_basic_cluster = False

    for eid, ep in non_zdo_endpoints.items():
        if ep.profile_id is not None:
            profile_ids.add(ep.profile_id)

        if hasattr(ep, "in_clusters") and CLUSTER_BASIC in ep.in_clusters:
            has_basic_cluster = True

    # Check profile types
    if profile_ids and all(pid == PROFILE_ZLL for pid in profile_ids):
        issues.append(
            {
                "severity": "warning",
                "category": "protocol",
                "message": (
                    "All endpoints use the ZigBee Light Link (ZLL) profile (0xC05E). "
                    "ZLL was merged into Zigbee 3.0 but older ZLL-only devices may "
                    "have limited Trust Center key update support."
                ),
            }
        )

    unknown_profiles = profile_ids - {PROFILE_HA, PROFILE_ZLL, PROFILE_SE, PROFILE_GP}
    for pid in unknown_profiles:
        issues.append(
            {
                "severity": "info",
                "category": "protocol",
                "message": f"Uses non-standard profile ID 0x{pid:04X}.",
            }
        )

    if not has_basic_cluster:
        issues.append(
            {
                "severity": "warning",
                "category": "protocol",
                "message": (
                    "No Basic cluster (0x0000) found on any endpoint. "
                    "Cannot read ZCL/stack version attributes for compliance verification."
                ),
            }
        )

    return issues


def _check_basic_cluster_cache(device: Any) -> tuple[list[dict[str, str]], dict]:
    """Check cached Basic cluster attributes for ZB3 indicators."""
    issues: list[dict[str, str]] = []
    basic_attrs: dict[str, Any] = {}

    # Find basic cluster on any endpoint
    basic = None
    for eid, ep in device.endpoints.items():
        if eid == 0:
            continue
        if hasattr(ep, "in_clusters") and CLUSTER_BASIC in ep.in_clusters:
            basic = ep.in_clusters[CLUSTER_BASIC]
            break

    if basic is None:
        return issues, basic_attrs

    # Read cached attribute values (AttributeCache supports dict-like access by attr ID)
    cache = getattr(basic, "_attr_cache", {})

    # Map attribute IDs to names for the Basic cluster
    # Standard Basic cluster attribute IDs:
    # 0x0000 = zcl_version, 0x0001 = app_version, 0x0002 = stack_version,
    # 0x0003 = hw_version, 0x0004 = manufacturer_name, 0x0005 = model_id,
    # 0x0007 = power_source, 0x4000 = sw_build_id
    attr_names = {
        0x0000: "zcl_version",
        0x0001: "app_version",
        0x0002: "stack_version",
        0x0003: "hw_version",
        0x0004: "manufacturer_name",
        0x0005: "model_id",
        0x0007: "power_source",
        0x4000: "sw_build_id",
    }

    for attr_id, attr_name in attr_names.items():
        if attr_id in cache:
            basic_attrs[attr_name] = cache[attr_id]

    # Evaluate what we found
    zcl_version = basic_attrs.get("zcl_version")
    stack_version = basic_attrs.get("stack_version")

    if zcl_version is not None:
        try:
            zcl_v = int(zcl_version)
            if zcl_v < 3:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "protocol",
                        "message": (
                            f"ZCL version is {zcl_v} (Zigbee 3.0 expects ZCL >= 3). "
                            f"This suggests a pre-Zigbee 3.0 device."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    if stack_version is not None:
        try:
            sv = int(stack_version)
            if sv < 2:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "protocol",
                        "message": (
                            f"Stack version is {sv} (Zigbee 3.0 expects >= 2). "
                            f"This suggests a pre-Zigbee 3.0 device."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    return issues, basic_attrs


def _check_signal_and_availability(device: Any) -> list[dict[str, str]]:
    """Check signal quality and device availability."""
    issues = []

    lqi = getattr(device, "lqi", None)
    if lqi is not None and lqi < 50:
        issues.append(
            {
                "severity": "warning",
                "category": "key_rotation",
                "message": (
                    f"Low link quality (LQI={lqi}). Device may not reliably "
                    f"receive the key update broadcast."
                ),
            }
        )

    rssi = getattr(device, "rssi", None)
    if rssi is not None and rssi < -90:
        issues.append(
            {
                "severity": "warning",
                "category": "key_rotation",
                "message": (
                    f"Weak signal (RSSI={rssi} dBm). Device may not reliably "
                    f"receive the key update broadcast."
                ),
            }
        )

    last_seen = getattr(device, "last_seen", None)
    if last_seen is not None:
        age_s = time.time() - last_seen
        if age_s > UNAVAILABLE_THRESHOLD_S:
            hours = int(age_s / 3600)
            issues.append(
                {
                    "severity": "critical",
                    "category": "key_rotation",
                    "message": (
                        f"Device not seen for {hours} hours. It is likely offline "
                        f"and will not receive the key update. After rotation it will "
                        f"need to be re-paired."
                    ),
                }
            )
    else:
        issues.append(
            {
                "severity": "info",
                "category": "key_rotation",
                "message": "No last_seen timestamp available for this device.",
            }
        )

    return issues


def _check_manufacturer_quirks(device: Any) -> list[dict[str, str]]:
    """Flag devices from manufacturers with known non-standard behavior."""
    issues = []

    manufacturer = getattr(device, "manufacturer", None) or ""

    for mfr_key, note in KNOWN_QUIRKY_MANUFACTURERS.items():
        if mfr_key.lower() in manufacturer.lower():
            issues.append(
                {
                    "severity": "warning",
                    "category": "key_rotation",
                    "message": note,
                }
            )
            break

    return issues


def _check_link_key(device: Any, key_table: list) -> list[dict[str, str]]:
    """Check if the device has an application link key with the trust center."""
    issues = []

    has_link_key = False
    for key in key_table:
        partner = getattr(key, "partner_ieee", None)
        if partner is not None and partner == device.ieee:
            has_link_key = True
            break

    if not has_link_key:
        issues.append(
            {
                "severity": "info",
                "category": "security",
                "message": (
                    "No dedicated Trust Center link key found for this device. "
                    "It likely joined using the well-known HA Trust Center link key, "
                    "which is standard for Zigbee 3.0."
                ),
            }
        )

    return issues


def _assess_rotation_risk(issues: list[dict[str, str]], device: Any) -> str:
    """Compute a key rotation risk level based on the collected issues."""
    has_critical = any(i["severity"] == "critical" for i in issues)
    warnings = [i for i in issues if i["severity"] == "warning"]
    has_key_rotation_warning = any(i["category"] == "key_rotation" for i in warnings)
    has_security_critical = any(
        i["severity"] == "critical" and i["category"] == "security" for i in issues
    )

    if has_security_critical:
        return "critical"
    if has_critical:
        return "high"
    if has_key_rotation_warning:
        return "medium"
    if warnings:
        return "medium"
    return "low"


def analyze_single_device(device: Any, key_table: list) -> dict[str, Any]:
    """Run all compliance checks on a single device."""
    issues: list[dict[str, str]] = []

    issues.extend(_check_node_descriptor(device))
    issues.extend(_check_endpoints(device))

    basic_issues, basic_attrs = _check_basic_cluster_cache(device)
    issues.extend(basic_issues)

    issues.extend(_check_signal_and_availability(device))
    issues.extend(_check_manufacturer_quirks(device))
    issues.extend(_check_link_key(device, key_table))

    risk = _assess_rotation_risk(issues, device)

    # Build device info
    nd = device.node_desc
    device_type = "unknown"
    is_mains_powered = None
    is_security_capable = None
    is_rx_on_when_idle = None

    if nd is not None:
        if nd.is_coordinator:
            device_type = "coordinator"
        elif nd.is_router:
            device_type = "router"
        elif nd.is_end_device:
            device_type = "end_device"
        is_mains_powered = nd.is_mains_powered
        is_security_capable = nd.is_security_capable
        is_rx_on_when_idle = nd.is_receiver_on_when_idle

    # Gather endpoint profiles
    profiles = []
    for eid, ep in device.endpoints.items():
        if eid == 0:
            continue
        pid = getattr(ep, "profile_id", None)
        profile_name = (
            PROFILE_NAMES.get(pid, f"0x{pid:04X}") if pid is not None else None
        )
        profiles.append(
            {
                "endpoint_id": eid,
                "profile": profile_name,
                "profile_id": f"0x{pid:04X}" if pid is not None else None,
                "device_type": f"0x{ep.device_type:04X}"
                if getattr(ep, "device_type", None) is not None
                else None,
                "in_clusters": sorted(getattr(ep, "in_clusters", {}).keys()),
                "out_clusters": sorted(getattr(ep, "out_clusters", {}).keys()),
            }
        )

    result = {
        "ieee": str(device.ieee),
        "nwk": f"0x{device.nwk:04X}",
        "manufacturer": getattr(device, "manufacturer", None),
        "model": getattr(device, "model", None),
        "device_type": device_type,
        "is_initialized": getattr(device, "is_initialized", None),
        "is_mains_powered": is_mains_powered,
        "is_security_capable": is_security_capable,
        "is_rx_on_when_idle": is_rx_on_when_idle,
        "lqi": getattr(device, "lqi", None),
        "rssi": getattr(device, "rssi", None),
        "rotation_risk": risk,
        "issues": issues,
        "endpoints": profiles,
    }

    if basic_attrs:
        result["basic_cluster_attributes"] = {
            k: str(v) if v is not None else None for k, v in basic_attrs.items()
        }

    return result


def analyze_network(app: Any) -> dict[str, Any]:
    """Analyze all devices on the network for ZB3 compliance and key rotation readiness."""
    key_table = getattr(app.state.network_info, "key_table", [])

    devices = []
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    total_issues = {"critical": 0, "warning": 0, "info": 0}

    for ieee, device in app.devices.items():
        # Skip the coordinator itself
        if device.nwk == 0x0000:
            continue

        analysis = analyze_single_device(device, key_table)
        devices.append(analysis)

        risk_counts[analysis["rotation_risk"]] += 1
        for issue in analysis["issues"]:
            total_issues[issue["severity"]] += 1

    # Sort: critical risk first, then high, medium, low
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    devices.sort(key=lambda d: risk_order.get(d["rotation_risk"], 4))

    # Build summary
    summary = {
        "total_devices": len(devices),
        "risk_breakdown": risk_counts,
        "issue_counts": total_issues,
        "ready_for_rotation": risk_counts["critical"] == 0,
    }

    if risk_counts["critical"] > 0:
        summary["recommendation"] = (
            f"{risk_counts['critical']} device(s) have critical issues that will "
            f"likely cause them to lose connectivity after key rotation. "
            f"Review the device list and consider re-pairing these devices afterward."
        )
    elif risk_counts["high"] > 0:
        summary["recommendation"] = (
            f"{risk_counts['high']} device(s) have high-risk issues. "
            f"Key rotation may work but increase the switch_delay and "
            f"monitor these devices closely."
        )
    elif risk_counts["medium"] > 0:
        summary["recommendation"] = (
            f"All devices appear compatible. {risk_counts['medium']} device(s) have "
            f"minor concerns. Consider a switch_delay of 60 seconds or more "
            f"for reliability."
        )
    else:
        summary["recommendation"] = (
            "All devices appear Zigbee 3.0 compliant with low rotation risk. "
            "The default settings should work."
        )

    return {
        "summary": summary,
        "devices": devices,
    }
