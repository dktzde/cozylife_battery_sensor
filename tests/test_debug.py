"""Debug summaries must not leak identity or values."""

from __future__ import annotations

import json

from cozylife_local.debug import summarize_dpids, summarize_frame


def test_valid_frame_keeps_its_shape() -> None:
    frame = {"cmd": 10, "res": 0, "sn": "123", "msg": {"attr": [4, 8], "data": {"8": 213, "4": 55}}}
    assert summarize_frame(json.dumps(frame).encode()) == {
        "cmd": 10,
        "res": 0,
        "msg": {"attr": [4, 8], "data_dpids": ["4", "8"]},
    }


def test_unexpected_fields_are_dropped() -> None:
    frame = {
        "cmd": "did-1234",
        "res": {"did": "x"},
        "msg": {"attr": [4, "did-1234"], "data": {"8": 1, "did-1234": 2}},
    }
    assert summarize_frame(json.dumps(frame).encode()) == {
        "msg": {"attr": [4], "data_dpids": ["8"]},
    }


def test_invalid_and_non_object_frames() -> None:
    assert summarize_frame(b"nope") == {"invalid_frame_bytes": 4}
    assert summarize_frame(b"[1]") == {"non_object_frame": "list"}


def test_dpids_are_sorted_numerically() -> None:
    assert summarize_dpids({"14": 1, "4": 2, "9": 3}) == ["4", "9", "14"]
