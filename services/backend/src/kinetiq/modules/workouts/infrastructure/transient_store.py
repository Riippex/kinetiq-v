import json
import logging
from uuid import UUID

from django.core.cache import cache
from django_redis import get_redis_connection

from kinetiq.modules.workouts.application.ports import (
    SessionTransientStore,
    TransientSessionUpdate,
)

logger = logging.getLogger(__name__)

TRANSIENT_KEY_PREFIX = "kinetiq:session:"
TRANSIENT_KEY_SUFFIX = ":transient"
CHANNEL_PREFIX = "kinetiq:session:"
CHANNEL_SUFFIX = ":stream"
DEFAULT_TTL_SECONDS = 3600


class RedisSessionTransientStore(SessionTransientStore):
    """Implementation of SessionTransientStore backed by Redis cache and Pub/Sub.

    All Redis operations are safely wrapped so that connection issues or missing
    keys cleanly fall back without throwing errors or interrupting database operations.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds

    def _get_key(self, session_id: UUID) -> str:
        return f"{TRANSIENT_KEY_PREFIX}{session_id}{TRANSIENT_KEY_SUFFIX}"

    def _get_channel(self, session_id: UUID) -> str:
        return f"{CHANNEL_PREFIX}{session_id}{CHANNEL_SUFFIX}"

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool:
        payload = {
            "session_id": str(update.session_id),
            "active_exercise_id": update.active_exercise_id,
            "current_repetitions": update.current_repetitions,
            "current_duration_seconds": update.current_duration_seconds,
            "pose_confidence": update.pose_confidence,
            "visibility_status": update.visibility_status,
            "timestamp": update.timestamp,
        }
        json_data = json.dumps(payload, sort_keys=True)
        key = self._get_key(update.session_id)
        channel = self._get_channel(update.session_id)

        try:
            cache.set(key, json_data, timeout=self._ttl_seconds)
            try:
                redis_conn = get_redis_connection("default")
                redis_conn.publish(channel, json_data)
            except Exception as pub_error:
                logger.warning("Redis PubSub publish failed for session %s: %s", update.session_id, pub_error)
            return True
        except Exception as error:
            logger.warning("Failed to store transient session update in Redis: %s", error)
            return False

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None:
        key = self._get_key(session_id)
        try:
            raw_data = cache.get(key)
            if raw_data is None:
                return None

            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            payload = json.loads(raw_data)
            return TransientSessionUpdate(
                session_id=UUID(payload["session_id"]),
                active_exercise_id=payload.get("active_exercise_id"),
                current_repetitions=payload.get("current_repetitions"),
                current_duration_seconds=payload.get("current_duration_seconds"),
                pose_confidence=payload.get("pose_confidence"),
                visibility_status=payload.get("visibility_status", "VISIBLE"),
                timestamp=payload.get("timestamp"),
            )
        except Exception as error:
            logger.warning("Failed to retrieve transient session update from Redis for %s: %s", session_id, error)
            return None
