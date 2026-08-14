import asyncio
import logging
import os

from redis.asyncio import Redis


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("npd-video-worker")

QUEUE_KEY = "npd:video-jobs:queue"


async def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis = Redis.from_url(redis_url, decode_responses=True)
    logger.info("worker_booted queue=%s", QUEUE_KEY)
    try:
        while True:
            item = await redis.blpop(QUEUE_KEY, timeout=5)
            if item is None:
                continue
            _, job_id = item
            # Task 11 will replace this placeholder with the resumable pipeline.
            logger.info("job_dequeued job_id=%s implementation=pending_task_11", job_id)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
