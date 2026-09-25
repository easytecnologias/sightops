import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import connector_service


def main() -> None:
    idle_script = connector_service._routeros_job_script_template(
        base_url="https://sightops.example",
        connector_id="perucaba",
        token="token",
        job=None,
    )
    assert 'interval=10s' in idle_script
    assert 'sightops-connector' in idle_script

    job = {
        "id": "job1",
        "type": "access_http_get",
        "payload": {
            "url": "http://10.10.10.175/cgi-bin/magicBox.cgi?action=getSystemInfo",
            "username": "admin",
            "password": "secret",
        },
    }
    script = connector_service._routeros_job_script_template(
        base_url="https://sightops.example",
        connector_id="perucaba",
        token="token",
        job=job,
    )
    assert "http-auth-scheme=digest" in script
    assert "output=user as-value" in script
    assert "/api/connectors/agent/routeros/jobs/job1/result-text" in script
    assert "access_http_get" in script

    post_job = {
        "id": "job2",
        "type": "access_http_post",
        "payload": {
            "url": "http://10.10.10.175/cgi-bin/AccessUser.cgi?action=removeMulti",
            "username": "admin",
            "password": "secret",
            "content_type": "application/json",
            "body": '{"UserIDList":["1001"]}',
        },
    }
    post_script = connector_service._routeros_job_script_template(
        base_url="https://sightops.example",
        connector_id="perucaba",
        token="token",
        job=post_job,
    )
    assert "http-method=post" in post_script
    assert "http-data=" in post_script
    assert "access_http_post" in post_script
    print("OK connector access_http_get/access_http_post job")


if __name__ == "__main__":
    main()
