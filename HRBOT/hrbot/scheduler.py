from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger


log = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')


@dataclass
class ScheduledItem:
    id: str
    channel_id: int
    content: str
    schedule_type: str  # 'once' | 'cron'
    when: Optional[datetime] = None
    cron: Optional[str] = None


class SchedulerService:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=JST)
        self.scheduler.start()

    def add_once(self, item_id: str, when: datetime, func: Callable, *args, **kwargs) -> None:
        trigger = DateTrigger(run_date=when.astimezone(JST))
        self.scheduler.add_job(func, trigger, id=item_id, args=args, kwargs=kwargs, replace_existing=True)

    def add_cron(self, item_id: str, cron_expr: str, func: Callable, *args, **kwargs) -> None:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=JST)
        self.scheduler.add_job(func, trigger, id=item_id, args=args, kwargs=kwargs, replace_existing=True)

    def remove(self, item_id: str) -> None:
        try:
            self.scheduler.remove_job(item_id)
        except Exception:
            pass

    def exists(self, item_id: str) -> bool:
        try:
            self.scheduler.get_job(item_id)
            return True
        except Exception:
            return False

