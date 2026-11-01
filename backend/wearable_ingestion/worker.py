"""MindBridge wearable worker.

Consumes the Redis Stream written by simulator.py (or a real-device bridge),
validates/normalises events, applies EWMA smoothing, persists raw + smoothed
values to PostgreSQL and maintains the Redis latest/recent/EWMA-state keys.
It also refreshes daily rollups and anomaly detection for patients it touched.

    python worker.py

Configuration comes from the repository-root .env (see .env.example).
"""

from __future__ import annotations

import logging
import os
import socket
import time

import psycopg2
import psycopg2.extras
import redis

from env_config import load_ingestion_environment

load_ingestion_environment(__file__)

from services import wearable_analytics, wearables  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WORKER] %(levelname)s %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("worker")

GROUP = os.getenv("WEARABLE_GROUP", "processor")
CONSUMER = os.getenv("WEARABLE_CONSUMER", f"{socket.gethostname()}-{os.getpid()}")
ROLLUP_INTERVAL = float(os.getenv("ROLLUP_INTERVAL_SECONDS", "60"))


def connect_redis() -> redis.Redis:
    backoff = 1.0
    while True:
        try:
            client = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")),
                                 decode_responses=True, socket_connect_timeout=5, socket_timeout=15)
            client.ping()
            wearables.ensure_group(client, wearables.STREAM, GROUP)
            log.info("Connected to Redis; consuming '%s' as group '%s'", wearables.STREAM, GROUP)
            return client
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis unavailable (%s); retrying in %.0fs", type(exc).__name__, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


def connect_db():
    backoff = 1.0
    while True:
        try:
            conn = psycopg2.connect(
                host=os.environ["INGESTION_DB_HOST"], port=os.getenv("INGESTION_DB_PORT", "6543"),
                dbname=os.getenv("INGESTION_DB_NAME", "postgres"), user=os.environ["INGESTION_DB_USER"],
                password=os.environ["INGESTION_DB_PASSWORD"], sslmode=os.getenv("INGESTION_DB_SSLMODE", "require"),
                connect_timeout=10, cursor_factory=psycopg2.extras.RealDictCursor)
            log.info("Connected to PostgreSQL")
            return conn
        except KeyError as exc:
            raise SystemExit(f"Missing database setting {exc}; set DB_* (or INGESTION_DB_*) in the root .env")
        except psycopg2.OperationalError:
            log.warning("PostgreSQL unavailable; retrying in %.0fs", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def refresh_analytics(conn, patients: set[int]) -> None:
    for pid in patients:
        try:
            wearable_analytics.rollup_patient(conn, pid)
            wearable_analytics.detect_anomalies(conn, pid)
        except Exception as exc:
            conn.rollback()
            log.warning("analytics refresh failed for a patient: %s", type(exc).__name__)


def run() -> None:
    r, conn = connect_redis(), connect_db()
    touched: set[int] = set()
    last_rollup = time.monotonic()
    while True:
        try:
            stats = wearables.consume_batch(r, conn, wearables.STREAM, GROUP, CONSUMER,
                                            on_stored=lambda res: touched.add(res["patient_id"]))
            if any(stats.values()):
                log.info("batch: %s", stats)
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis error (%s); reconnecting", type(exc).__name__)
            r = connect_redis()
        except psycopg2.Error as exc:
            log.warning("PostgreSQL error (%s); reconnecting", type(exc).__name__)
            try:
                conn.close()
            except Exception:
                pass
            conn = connect_db()
        except Exception as exc:
            log.error("unexpected error: %s", type(exc).__name__)
            time.sleep(1)
        if touched and time.monotonic() - last_rollup >= ROLLUP_INTERVAL:
            refresh_analytics(conn, touched)
            touched.clear()
            last_rollup = time.monotonic()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Worker stopped by user.")
