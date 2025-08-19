from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .scheduler import ScheduledItem


DEFAULT_DB_PATH = os.path.join(os.getcwd(), 'data', 'schedules.json')


@dataclass
class ScheduleRecord:
    id: str
    channel_id: int
    content: str
    type: str  # 'once' | 'cron'
    when: Optional[str] = None  # ISO
    cron: Optional[str] = None


class StorageService:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if not os.path.exists(self.db_path):
            self._write_all({})

    def _read_all(self) -> Dict[str, ScheduleRecord]:
        with self._lock:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        out: Dict[str, ScheduleRecord] = {}
        for k, v in raw.items():
            out[k] = ScheduleRecord(**v)
        return out

    def _write_all(self, data: Dict[str, ScheduleRecord]) -> None:
        with self._lock:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in data.items()}, f, ensure_ascii=False, indent=2)

    def list(self) -> List[ScheduleRecord]:
        return list(self._read_all().values())

    def get(self, schedule_id: str) -> Optional[ScheduleRecord]:
        return self._read_all().get(schedule_id)

    def upsert(self, record: ScheduleRecord) -> None:
        data = self._read_all()
        data[record.id] = record
        self._write_all(data)

    def delete(self, schedule_id: str) -> bool:
        data = self._read_all()
        existed = schedule_id in data
        if existed:
            data.pop(schedule_id)
            self._write_all(data)
        return existed

