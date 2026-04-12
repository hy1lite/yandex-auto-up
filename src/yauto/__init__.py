"""yandex auto up package."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["__display_name__", "__github_repo__", "__tagline__", "__version__", "get_version_metadata"]


@lru_cache(maxsize=1)
def get_version_metadata() -> dict[str, Any]:
	return json.loads(Path(__file__).with_name("version.json").read_text(encoding="utf-8"))


_METADATA = get_version_metadata()

__version__ = str(_METADATA["version"])
__display_name__ = str(_METADATA.get("display_name", "yandex-auto-up"))
__tagline__ = str(_METADATA.get("tagline", "Low-resource Yandex Cloud watchdog"))
__github_repo__ = str(_METADATA.get("github_repo", ""))
