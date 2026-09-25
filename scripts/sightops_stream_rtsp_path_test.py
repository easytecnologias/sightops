import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_stream_service import _stream_rtsp_path_for_camera


def assert_equal(actual: str, expected: str) -> None:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def main() -> None:
    assert_equal(
        _stream_rtsp_path_for_camera(vendor="Intelbras", model="VIPC-1230-B-G2", subtype=1),
        "/cam/realmonitor?channel=1&subtype=1",
    )
    assert_equal(
        _stream_rtsp_path_for_camera(vendor="", model="VIPC-1230-B-G2", subtype=1),
        "/cam/realmonitor?channel=1&subtype=1",
    )
    assert_equal(
        _stream_rtsp_path_for_camera(vendor="Hikvision", model="DS-2CD1021G0-I", subtype=1),
        "/Streaming/Channels/102",
    )
    assert_equal(
        _stream_rtsp_path_for_camera(vendor="", model="IPC-B121H-L", subtype=0),
        "/Streaming/Channels/101",
    )
    print("ok")


if __name__ == "__main__":
    main()
