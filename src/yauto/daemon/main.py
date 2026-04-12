"""Daemon entry point."""

from __future__ import annotations

import logging

from yauto.config.repository import ConfigRepository
from yauto.daemon.service import MonitorDaemon
from yauto.storage.repository import RuntimeRepository


def main() -> None:
    config_repo = ConfigRepository()
    config = config_repo.load_app_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    MonitorDaemon(config_repo=config_repo, runtime_repo=RuntimeRepository(config_repo.paths)).run()


if __name__ == "__main__":
    main()
