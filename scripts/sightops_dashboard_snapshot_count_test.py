from __future__ import annotations

from app.services import dashboard_service


def main() -> None:
    original_resolver = dashboard_service.resolve_snapshot_file

    try:
        rows = [
            {"ip": "10.1.1.10", "status": "online", "local": "SITE", "modelo": "X"},
            {"ip": "10.1.1.11", "status": "online", "local": "SITE", "modelo": "X"},
            {"ip": "10.1.1.12", "status": "online", "local": "SITE", "modelo": "X", "imgbb_thumb_url": "https://img.example/t.jpg"},
            {"ip": "10.1.1.13", "status": "online", "local": "SITE", "modelo": "X", "snapshot_file": "snapshot/manual.jpg"},
        ]

        dashboard_service.resolve_snapshot_file = lambda path_hint="", ip="": object() if ip == "10.1.1.10" else None
        gaps = dashboard_service._missing_counts(rows, resolve_local_snapshots=True)
        assert gaps["missing_snapshot"] == 1, gaps
    finally:
        dashboard_service.resolve_snapshot_file = original_resolver

    print("OK dashboard snapshot count")


if __name__ == "__main__":
    main()
