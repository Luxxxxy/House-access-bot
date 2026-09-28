"""Простой FSM в памяти (python-max-bot не даёт FSMContext)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FSMRecord:
    state: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)


class MemoryFSM:
    def __init__(self) -> None:
        self._records: dict[int, FSMRecord] = {}

    def get_state(self, user_id: int | None) -> Any | None:
        if user_id is None:
            return None
        record = self._records.get(user_id)
        return record.state if record else None

    def get_data(self, user_id: int) -> dict[str, Any]:
        record = self._records.get(user_id)
        return dict(record.data) if record else {}

    def set_state(self, user_id: int, state: Any | None, **data: Any) -> None:
        record = self._records.setdefault(user_id, FSMRecord())
        record.state = state
        if data:
            record.data.update(data)

    def update_data(self, user_id: int, **data: Any) -> None:
        record = self._records.setdefault(user_id, FSMRecord())
        record.data.update(data)

    def clear(self, user_id: int | None) -> None:
        if user_id is not None:
            self._records.pop(user_id, None)


fsm = MemoryFSM()
