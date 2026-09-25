import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.zabbix_monitoring_service import find_orphan_hostids


def test_removes_host_whose_onu_is_no_longer_active():
    current_hosts = [
        {"hostid": "10", "host": "SIGHTOPS.default.ONU.aaaa1111"},
        {"hostid": "11", "host": "SIGHTOPS.default.ONU.bbbb2222"},
    ]
    technical_names = {"SIGHTOPS.default.ONU.aaaa1111": {}}
    orphans = find_orphan_hostids(current_hosts, technical_names, "default", ("olt", "onu"))
    assert orphans == ["11"]


def test_keeps_hosts_still_active():
    current_hosts = [{"hostid": "10", "host": "SIGHTOPS.default.ONU.aaaa1111"}]
    technical_names = {"SIGHTOPS.default.ONU.aaaa1111": {}}
    assert find_orphan_hostids(current_hosts, technical_names, "default", ("olt", "onu")) == []


def test_ignores_hosts_of_other_entity_types_not_in_this_sync_call():
    current_hosts = [{"hostid": "20", "host": "SIGHTOPS.default.CAMERA.cccc3333"}]
    orphans = find_orphan_hostids(current_hosts, {}, "default", ("olt", "onu"))
    assert orphans == []


def test_removes_all_when_no_entities_left_for_that_type():
    current_hosts = [
        {"hostid": "10", "host": "SIGHTOPS.default.ONU.aaaa1111"},
        {"hostid": "11", "host": "SIGHTOPS.default.OLT.bbbb2222"},
    ]
    orphans = find_orphan_hostids(current_hosts, {}, "default", ("olt", "onu"))
    assert set(orphans) == {"10", "11"}


def test_scopes_orphan_detection_by_tenant():
    current_hosts = [{"hostid": "30", "host": "SIGHTOPS.otherclient.ONU.dddd4444"}]
    orphans = find_orphan_hostids(current_hosts, {}, "default", ("olt", "onu"))
    assert orphans == []


def main() -> None:
    test_removes_host_whose_onu_is_no_longer_active()
    test_keeps_hosts_still_active()
    test_ignores_hosts_of_other_entity_types_not_in_this_sync_call()
    test_removes_all_when_no_entities_left_for_that_type()
    test_scopes_orphan_detection_by_tenant()
    print("OK: sightops_zabbix_orphan_hosts_test")


if __name__ == "__main__":
    main()
