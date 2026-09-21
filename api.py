"""Compat shim.

Some older docs / deployments run the project with:

    uvicorn api:app --reload

The project was refactored to use `app.main:app` as the canonical entrypoint.
This file keeps backward compatibility so existing commands keep working.
"""

from app.main import app  # noqa: F401
