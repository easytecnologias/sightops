from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.endpoints import deployments


def test_live_authoritative_grid_preserves_snapshots_for_remaining_channels() -> None:
    original_reader = deployments._read_recorder_rows
    try:
        deployments._read_recorder_rows = lambda source: [
            {
                "host": "10.0.0.10",
                "channel": 1,
                "title": "Camera removida",
                "camera_ip": "10.0.1.1",
                "snapshot_url": "/snapshots/ch01.jpg",
            },
            {
                "host": "10.0.0.10",
                "channel": 2,
                "title": "Camera mantida",
                "camera_ip": "10.0.1.2",
                "camera_model": "VIP-1230",
                "camera_mac": "aa:bb:cc:dd:ee:ff",
                "snapshot_url": "/snapshots/ch02.jpg",
                "imgbb_url": "https://imgbb.example/ch02",
                "imgbb_thumb_url": "https://imgbb.example/ch02-thumb",
            },
        ]

        rows = deployments._recorder_channel_grid(
            "nvr",
            "10.0.0.10",
            total=2,
            live_used={
                2: {
                    "title": "Camera mantida ao vivo",
                    "camera_ip": "10.0.1.2",
                    "camera_model": "VIP-1230",
                    "camera_mac": "aa:bb:cc:dd:ee:ff",
                }
            },
            live_authoritative=True,
        )
    finally:
        deployments._read_recorder_rows = original_reader

    assert rows[0]["channel"] == 1
    assert rows[0]["used"] is False
    assert rows[0]["snapshot_url"] == ""
    assert rows[1]["channel"] == 2
    assert rows[1]["used"] is True
    assert rows[1]["snapshot_url"] == "/snapshots/ch02.jpg"
    assert rows[1]["imgbb_url"] == "https://imgbb.example/ch02"
    assert rows[1]["imgbb_thumb_url"] == "https://imgbb.example/ch02-thumb"


if __name__ == "__main__":
    test_live_authoritative_grid_preserves_snapshots_for_remaining_channels()
