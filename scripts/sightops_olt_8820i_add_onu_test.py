import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli.tools.olt_8820i_add_onu import OnuAddError, resolve_current_serno_id


def _discovered(*entries):
    return [{"serno_id": sid, "serial": serial} for sid, serial in entries]


def test_uses_fresh_serno_id_when_serial_matches():
    discovered = _discovered((72, "ITBS0A488C12"), (73, "8B3E3755"))
    assert resolve_current_serno_id(discovered, "itbs0a488c12", 999) == 72


def test_falls_back_to_serno_id_when_no_serial_given():
    discovered = _discovered((72, "ITBS0A488C12"))
    assert resolve_current_serno_id(discovered, "", 72) == 72


def test_falls_back_to_serno_id_when_serial_not_found_but_id_still_present():
    discovered = _discovered((72, "ITBS0A488C12"))
    assert resolve_current_serno_id(discovered, "SERIAL-NOT-IN-LIST", 72) == 72


def test_raises_actionable_error_when_id_expired_and_serial_gone():
    discovered = _discovered((99, "SOMEOTHERSERIAL"))
    try:
        resolve_current_serno_id(discovered, "ITBS0A488C12", 72)
        assert False, "esperava OnuAddError"
    except OnuAddError as e:
        assert "ITBS0A488C12" in str(e)
        assert "descoberta" in str(e).lower()


def main() -> None:
    test_uses_fresh_serno_id_when_serial_matches()
    test_falls_back_to_serno_id_when_no_serial_given()
    test_falls_back_to_serno_id_when_serial_not_found_but_id_still_present()
    test_raises_actionable_error_when_id_expired_and_serial_gone()
    print("OK: sightops_olt_8820i_add_onu_test")


if __name__ == "__main__":
    main()
