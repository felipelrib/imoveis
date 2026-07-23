import logging

from celery.beat import PersistentScheduler, ScheduleEntry

from infra.redis_client import get_redis

logger = logging.getLogger(__name__)


class RedisAwareScheduler(PersistentScheduler):
    """A Celery Beat scheduler that dynamically reads intervals from Redis.

    Before submitting a task, it checks Redis for `scheduler:interval:<platform>`.
    If the interval has changed, it updates the in-memory schedule and reschedules
    the task, avoiding the need to restart the beat process.
    """

    def apply_entry(self, entry: ScheduleEntry, producer=None):
        r = get_redis()

        # Check if this task is a scraper task with dynamic interval
        if entry.name.startswith("scrape-"):
            platform = entry.name.replace("scrape-", "")
            override = r.get(f"scheduler:interval:{platform}")

            if override is not None:
                try:
                    new_interval = int(override)
                    if new_interval <= 0:
                        # Interval <= 0 means disabled, skip sending
                        logger.info("redis_scheduler_skipped", task=entry.name, reason="disabled_via_redis")
                        return

                    # Celery schedule is in seconds
                    new_interval_sec = new_interval * 60

                    if entry.schedule.run_every.total_seconds() != new_interval_sec:
                        logger.info(
                            "redis_scheduler_updated",
                            task=entry.name,
                            old=entry.schedule.run_every.total_seconds(),
                            new=new_interval,
                        )
                        from celery.schedules import schedule
                        entry.schedule = schedule(run_every=new_interval_sec)

                        # Reschedule it
                        self._maybe_sync()
                except ValueError:
                    logger.warning("redis_scheduler_invalid_override", task=entry.name, override=override)

        return super().apply_entry(entry, producer=producer)
