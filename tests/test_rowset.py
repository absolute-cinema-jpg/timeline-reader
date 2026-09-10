"""RowSet: delete / undo / reset over keyed rows."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline_reader.rowset import RowSet


def test_delete_by_display_position_maps_to_keys():
    rs = RowSet()
    keys = ["a", "b", "c", "d"]
    # Delete the 1st and 3rd visible rows -> keys a and c.
    assert rs.delete_display([0, 2], keys) == 2
    assert rs.active_items(keys, keys) == ["b", "d"]
    assert rs.has_deletions and rs.can_undo


def test_undo_is_one_step_per_action():
    rs = RowSet()
    keys = ["a", "b", "c", "d"]
    rs.delete(["a"])
    active = rs.active_keys(keys)              # ["b", "c", "d"]
    rs.delete_display([0], active)             # deletes "b"
    assert rs.active_keys(keys) == ["c", "d"]
    assert rs.undo() == 1                      # brings back "b"
    assert rs.active_keys(keys) == ["b", "c", "d"]
    assert rs.undo() == 1                      # brings back "a"
    assert rs.active_keys(keys) == keys
    assert rs.undo() == 0                      # nothing left to undo


def test_reset_restores_everything():
    rs = RowSet()
    keys = list(range(5))
    rs.delete_display([0, 1, 2], keys)
    assert rs.active_keys(keys) == [3, 4]
    rs.reset()
    assert rs.active_keys(keys) == keys
    assert not rs.has_deletions and not rs.can_undo


def test_deleting_already_deleted_is_noop():
    rs = RowSet()
    rs.delete(["x"])
    assert rs.delete(["x"]) == 0  # not double-counted, no new undo entry
    assert rs.undo() == 1
    assert not rs.has_deletions


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")
