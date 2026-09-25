import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sightops_ruijie_vpn_sync import config_hash, plan_actions


def test_creates_container_for_new_connector():
    desired = [{"id": "abc", "vpn_username": "sightops", "vpn_password": "x", "vpn_config": "cfg"}]
    plan = plan_actions(desired, running_ids=[], cached_hashes={})
    assert plan["create"] == ["abc"]
    assert plan["recreate"] == []
    assert plan["remove"] == []
    assert plan["noop"] == []


def test_noop_when_hash_matches():
    desired = [{"id": "abc", "vpn_username": "sightops", "vpn_password": "x", "vpn_config": "cfg"}]
    h = config_hash("cfg", "sightops", "x")
    plan = plan_actions(desired, running_ids=["abc"], cached_hashes={"abc": h})
    assert plan["noop"] == ["abc"]
    assert plan["create"] == plan["recreate"] == plan["remove"] == []


def test_recreates_when_config_changed():
    desired = [{"id": "abc", "vpn_username": "sightops", "vpn_password": "x", "vpn_config": "cfg-novo"}]
    stale_hash = config_hash("cfg-velho", "sightops", "x")
    plan = plan_actions(desired, running_ids=["abc"], cached_hashes={"abc": stale_hash})
    assert plan["recreate"] == ["abc"]
    assert plan["create"] == plan["remove"] == plan["noop"] == []


def test_recreates_when_password_changed_even_if_config_text_same():
    desired = [{"id": "abc", "vpn_username": "sightops", "vpn_password": "nova-senha", "vpn_config": "cfg"}]
    stale_hash = config_hash("cfg", "sightops", "senha-velha")
    plan = plan_actions(desired, running_ids=["abc"], cached_hashes={"abc": stale_hash})
    assert plan["recreate"] == ["abc"]


def test_removes_container_whose_connector_no_longer_has_vpn():
    plan = plan_actions(desired=[], running_ids=["abc"], cached_hashes={"abc": "whatever"})
    assert plan["remove"] == ["abc"]
    assert plan["create"] == plan["recreate"] == plan["noop"] == []


def test_multiple_connectors_mixed_states():
    desired = [
        {"id": "new1", "vpn_username": "u", "vpn_password": "p", "vpn_config": "c1"},
        {"id": "same1", "vpn_username": "u", "vpn_password": "p", "vpn_config": "c2"},
        {"id": "changed1", "vpn_username": "u", "vpn_password": "p", "vpn_config": "c3-novo"},
    ]
    cached = {
        "same1": config_hash("c2", "u", "p"),
        "changed1": config_hash("c3-velho", "u", "p"),
        "gone1": "irrelevante",
    }
    plan = plan_actions(desired, running_ids=["same1", "changed1", "gone1"], cached_hashes=cached)
    assert plan["create"] == ["new1"]
    assert plan["recreate"] == ["changed1"]
    assert plan["remove"] == ["gone1"]
    assert plan["noop"] == ["same1"]


def main() -> None:
    test_creates_container_for_new_connector()
    test_noop_when_hash_matches()
    test_recreates_when_config_changed()
    test_recreates_when_password_changed_even_if_config_text_same()
    test_removes_container_whose_connector_no_longer_has_vpn()
    test_multiple_connectors_mixed_states()
    print("OK: sightops_ruijie_vpn_sync_test")


if __name__ == "__main__":
    main()
