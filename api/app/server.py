"""Binds the port. Everything else lives in `main.py`.

Run it as `python -m app.server`, which is what `scripts/dev.sh` does. Going
through here rather than pointing uvicorn straight at `app.main:create_app`
means the `.env` is loaded and `API_PORT` is honoured.
"""

from __future__ import annotations

import uvicorn

from app.config import Config
from app.main import create_app


def main() -> None:
    config = Config.from_env()
    # 0.0.0.0 because this runs in a container, where binding loopback would
    # make the port unreachable from outside it.
    uvicorn.run(create_app(config), host="0.0.0.0", port=config.api_port)


if __name__ == "__main__":
    main()
