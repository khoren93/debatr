"""OpenRouter's free-model limit on the system key, shared by every user.

OpenRouter allows 20 requests a minute to `:free` models per account, whatever the key, so all
Free Router and `:free` debates that run on the system key share it. Instead of a burst of 429s
(each of which would stop a debate), a turn waits for a slot in the current clock minute
(`FREE_MODELS_PER_MINUTE`, a fixed window in Redis). Own keys have their own account's limit.
"""

import logging
import random
import time

from app.core.config import settings
from app.core.redis import free_models_window_key, get_sync_redis
from app.services.free_router import FREE_SUFFIX, is_free_router

logger = logging.getLogger(__name__)


def is_free_model(model_id: str) -> bool:
    return model_id.endswith(FREE_SUFFIX) or is_free_router(model_id)


def wait_for_slot(deadline: float) -> bool:
    """Take a free-model request slot, waiting for the next minute when this one is full.
    False when no slot comes before `deadline` (`time.monotonic()`)."""
    limit = settings.FREE_MODELS_PER_MINUTE
    if limit <= 0:
        return True
    redis = get_sync_redis()
    while True:
        now = time.time()
        minute = int(now // 60)
        key = free_models_window_key(minute)
        taken = int(redis.incr(key))
        if taken == 1:
            redis.expire(key, 120)
        if taken <= limit:
            return True
        wait = (minute + 1) * 60 - now + random.uniform(0.0, 3.0)  # spread the next minute
        if time.monotonic() + wait > deadline:
            return False
        logger.info("Free-model slots of this minute are taken, waiting %.0f s", wait)
        time.sleep(wait)
