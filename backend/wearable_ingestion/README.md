# Wearable ingestion

```text
simulator.py (or a device bridge)
      | XADD  Redis Stream "wearable:events"  (durable, replayable)
      v
worker.py  --- validate/normalise (services/wearables.py)
      |        time-aware EWMA (services/ewma.py)
      |-> PostgreSQL wearable_data   raw values + smoothed values + provenance (idempotent on event_id)
      |-> Redis  patient:<id>:vitals:latest | :vitals:recent | :ewma:*   (live reads, no PostgreSQL needed)
      '-> every ROLLUP_INTERVAL_SECONDS: wearable_daily rollups + wearable_anomalies
```

Run the seed once first. It creates/reuses one benchmark patient, writes its ID
to the ignored `.benchmark_patient_id` file, and stores account credentials in
the ignored `.benchmark_credentials` file. Re-running it reuses the same
accounts and does not append duplicate fixture context.

Run (repository root `.env` is loaded automatically; Redis/Neo4j come from `docker compose up -d redis neo4j`):

```bash
./scripts/create_demo_patient.sh
cd backend/wearable_ingestion
python worker.py        # terminal 1: start the consumer first
python simulator.py     # terminal 2: synthetic events
python backfill.py      # optional: recompute smoothed values / rollups / anomalies for stored rows
```

Behaviour worth knowing

* Every simulator event carries `"simulation": true` and `"source": "simulator"`; this is stored as
  `wearable_data.is_simulated` and propagated to rollups, anomalies, context text and Neo4j. Real device
  events must send `"simulation": false, "source": "device"`.
* Simulator and worker use the patient ID created by the seed script. While that benchmark ID is set,
  the worker sends events for any other patient to the dead-letter stream instead of storing them.
  `BENCHMARK_PATIENT_ID` may set the ID for a standalone run, but if the seed file exists it must match.
* EWMA is time-aware (`alpha = 1 - exp(-dt/tau)`). Gaps over `EWMA_MAX_GAP_SECONDS` re-seed the state,
  out-of-order samples are stored but do not move it, outliers are flagged (`quality_flags`) and kept out of
  the state, and a sustained level shift is accepted after `EWMA_OUTLIER_RESEED_AFTER` samples.
  Sleep and screen time are daily aggregates: they are smoothed across days in `wearable_daily`, not per event.
* Invalid events go to the dead-letter stream `wearable:dead`; PostgreSQL failures leave the message
  pending and it is retried (the stream is not lost while the worker is down).
* `test_simulator.py` (offline) is kept; the integration checks live in `python -m backend_tests`.
* `subscriber_postgres.py`, `subscriber_redis_cache.py` and `test_pipeline.py` are the previous Pub/Sub
  implementation. They are superseded by `worker.py` and are no longer used (safe to delete).
