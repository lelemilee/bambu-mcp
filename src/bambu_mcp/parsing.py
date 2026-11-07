"""Turn the printer's raw MQTT report into small, readable dicts.

Field names follow the community-documented protocol
(https://github.com/Doridian/OpenBambuAPI). They are not official and may
differ slightly on the P2S, so every lookup is defensive.
"""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial report into the cached full state (in place)."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _num(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _color(raw: Any) -> str | None:
    """'FF6A13FF' (RRGGBBAA) -> '#FF6A13'."""
    if not isinstance(raw, str) or len(raw) < 6:
        return None
    return "#" + raw[:6].upper()


def parse_status(state: dict[str, Any]) -> dict[str, Any]:
    p = state.get("print", {})
    return {
        "state": p.get("gcode_state"),  # IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED
        "job": p.get("subtask_name") or None,
        "progress_percent": _num(p.get("mc_percent")),
        "remaining_minutes": _num(p.get("mc_remaining_time")),
        "layer": _num(p.get("layer_num")),
        "total_layers": _num(p.get("total_layer_num")),
        "nozzle_temp": _num(p.get("nozzle_temper")),
        "nozzle_target": _num(p.get("nozzle_target_temper")),
        "bed_temp": _num(p.get("bed_temper")),
        "bed_target": _num(p.get("bed_target_temper")),
        "chamber_temp": _num(p.get("chamber_temper")),
        "error_code": _num(p.get("print_error")) or None,
        "wifi_signal": p.get("wifi_signal"),
    }


def _parse_tray(tray: dict[str, Any], slot_label: str, index: int | None) -> dict[str, Any]:
    material = tray.get("tray_type") or None
    remain = _num(tray.get("remain"))
    tag = tray.get("tray_uuid") or tray.get("tag_uid")
    if tag and set(str(tag)) <= {"0"}:
        tag = None
    return {
        "slot": slot_label,
        "tray_index": index,  # value to use in ams_mapping
        "empty": material is None,
        "material": material,
        "name": tray.get("tray_sub_brands") or None,
        "color": _color(tray.get("tray_color")),
        # -1 means the printer doesn't know (usually a non-RFID spool).
        "remaining_percent": remain if remain is not None and remain >= 0 else None,
        "rfid": tag,
        "nozzle_temp_range": [
            _num(tray.get("nozzle_temp_min")),
            _num(tray.get("nozzle_temp_max")),
        ],
    }


def valid_tray_indexes(ams: dict[str, Any]) -> set[int]:
    """Tray indexes that currently hold filament (usable in ams_mapping)."""
    slots = [s for u in ams["units"] for s in u["slots"]]
    if ams.get("external_spool"):
        slots.append(ams["external_spool"])
    return {s["tray_index"] for s in slots if not s["empty"] and s["tray_index"] is not None}


def parse_ams(state: dict[str, Any]) -> dict[str, Any]:
    p = state.get("print", {})
    ams_root = p.get("ams") or {}
    units = []
    for unit in ams_root.get("ams", []) or []:
        unit_id = str(unit.get("id", len(units)))
        unit_num = int(unit_id) if unit_id.isdigit() else None
        trays = []
        for i, t in enumerate(unit.get("tray", []) or []):
            raw_id = _num(t.get("id"))
            tray_num = int(raw_id) if raw_id is not None else i
            label = f"AMS{unit_num + 1 if unit_num is not None else unit_id}-{tray_num + 1}"
            index = unit_num * 4 + tray_num if unit_num is not None else None
            trays.append(_parse_tray(t, label, index))
        units.append(
            {
                "ams": unit_id,
                "humidity_level": _num(unit.get("humidity")),  # raw 1-5 index from the printer
                "humidity_percent": _num(unit.get("humidity_raw")),
                "temp": _num(unit.get("temp")),
                "slots": trays,
            }
        )
    external = p.get("vt_tray")
    return {
        "units": units,
        "external_spool": _parse_tray(external, "External", 254) if isinstance(external, dict) else None,
        "active_tray": ams_root.get("tray_now"),
    }
