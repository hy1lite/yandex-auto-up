"""Runtime state and event persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yauto.models import AppState, EventRecord
from yauto.paths import AppPaths, build_paths, ensure_layout


class RuntimeRepository:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or build_paths()
        ensure_layout(self.paths)

    def load_state(self) -> AppState:
        if not self.paths.state_file.exists():
            return AppState()
        with self.paths.state_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return AppState.model_validate(payload)

    def save_state(self, state: AppState) -> None:
        self._write_json_atomic(self.paths.state_file, state.model_dump(mode="json"))

    def append_event(self, event: EventRecord) -> None:
        with self.paths.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")

    def tail_events(self, limit: int = 20) -> list[EventRecord]:
        if not self.paths.events_file.exists():
            return []
        lines = self.paths.events_file.read_text(encoding="utf-8").splitlines()
        selected = lines[-limit:]
        events: list[EventRecord] = []
        for line in selected:
            if not line.strip():
                continue
            events.append(EventRecord.model_validate(json.loads(line)))
        return events

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
