from bambu_mcp.parsing import deep_merge, parse_ams, parse_status, valid_tray_indexes

REPORT = {
    "print": {
        "gcode_state": "RUNNING",
        "subtask_name": "okaeri_cap",
        "mc_percent": 42,
        "mc_remaining_time": 37,
        "nozzle_temper": 219.8,
        "bed_temper": "55",
        "print_error": 0,
        "ams": {
            "tray_now": "1",
            "ams": [
                {
                    "id": "0",
                    "humidity": "4",
                    "humidity_raw": "38",
                    "temp": "27.5",
                    "tray": [
                        {"id": "0", "tray_type": "PLA", "tray_sub_brands": "PLA Basic",
                         "tray_color": "FF6A13FF", "remain": 80,
                         "tray_uuid": "A1B2C3", "nozzle_temp_min": "190", "nozzle_temp_max": "230"},
                        {"id": "1", "tray_type": "PETG", "tray_color": "000000FF", "remain": -1,
                         "tray_uuid": "00000000000000000000000000000000"},
                        {"id": "2"},
                    ],
                }
            ],
        },
        "vt_tray": {"id": "254", "tray_type": "", "remain": 0},
    }
}


def test_status():
    s = parse_status(REPORT)
    assert s["state"] == "RUNNING"
    assert s["progress_percent"] == 42
    assert s["bed_temp"] == 55
    assert s["error_code"] is None


def test_ams_slots():
    ams = parse_ams(REPORT)
    unit = ams["units"][0]
    assert unit["humidity_percent"] == 38
    pla, petg, empty = unit["slots"]
    assert pla == {
        "slot": "AMS1-1", "tray_index": 0, "empty": False, "material": "PLA", "name": "PLA Basic",
        "color": "#FF6A13", "remaining_percent": 80, "rfid": "A1B2C3",
        "nozzle_temp_range": [190, 230],
    }
    assert petg["remaining_percent"] is None  # -1 means unknown
    assert petg["rfid"] is None  # all-zero tag means no RFID
    assert empty["empty"] is True and empty["slot"] == "AMS1-3"
    assert ams["external_spool"]["empty"] is True
    assert ams["active_tray"] == "1"
    assert petg["tray_index"] == 1
    assert valid_tray_indexes(ams) == {0, 1}


def test_deep_merge_keeps_old_fields():
    state = {"print": {"gcode_state": "IDLE", "mc_percent": 0}}
    deep_merge(state, {"print": {"mc_percent": 5}})
    assert state == {"print": {"gcode_state": "IDLE", "mc_percent": 5}}


def test_missing_everything():
    assert parse_ams({})["units"] == []
    assert parse_status({})["state"] is None
