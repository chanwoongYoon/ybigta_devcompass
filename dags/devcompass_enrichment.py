import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from airflow.sdk import dag, task

from devcompass.enrichment import JobRoleClassifier, SkillExtractor
from devcompass.storage import EnrichmentRepository


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEVCOMPASS_DSN = os.environ.get(
    "DEVCOMPASS_DSN", "postgresql://localhost/devcompass"
)
ROLE_MODEL_VERSION = os.environ.get(
    "DEVCOMPASS_ROLE_MODEL_VERSION", "job-role-svc-v1"
)
ROLE_MODEL_PATH = Path(
    os.environ.get(
        "DEVCOMPASS_ROLE_MODEL_PATH",
        str(PROJECT_DIR / "experiment" / "job_role_svc_v1.joblib"),
    )
)
ROLE_BATCH_SIZE = int(os.environ.get("DEVCOMPASS_ROLE_BATCH_SIZE", "250"))
SKILL_EXTRACTOR_VERSION = os.environ.get(
    "DEVCOMPASS_SKILL_EXTRACTOR_VERSION", "tech-dictionary-v1"
)


def connect():
    return psycopg.connect(DEVCOMPASS_DSN)


@dag(
    dag_id="devcompass_job_enrichment",
    schedule=None,
    start_date=datetime(2026, 8, 14, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "devcompass",
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["devcompass", "enrichment", "svc", "postgresql"],
)
def devcompass_job_enrichment():
    @task
    def select_targets():
        with connect() as connection:
            history_ids = EnrichmentRepository(
                connection
            ).list_enrichment_target_history_ids(
                ROLE_MODEL_VERSION,
                SKILL_EXTRACTOR_VERSION,
            )
        return [
            history_ids[index : index + ROLE_BATCH_SIZE]
            for index in range(0, len(history_ids), ROLE_BATCH_SIZE)
        ]

    @task
    def prepare_enrichment(history_ids):
        with connect() as connection:
            return EnrichmentRepository(connection).prepare_enrichment_batch(
                history_ids=history_ids,
                role_model_version=ROLE_MODEL_VERSION,
                skill_extractor_version=SKILL_EXTRACTOR_VERSION,
            )

    @task
    def classify_job_role(items):
        enrichment_ids = [item["enrichment_id"] for item in items]
        if not enrichment_ids:
            return {"processed": 0}
        try:
            with connect() as connection:
                repository = EnrichmentRepository(connection)
                inputs = repository.get_pending_role_inputs(enrichment_ids)
                if not inputs:
                    return {"processed": 0}
                classifier = JobRoleClassifier(
                    ROLE_MODEL_PATH,
                    expected_version=ROLE_MODEL_VERSION,
                )
                predictions = classifier.predict(
                    [item["title"] for item in inputs]
                )
                rows = [
                    dict(prediction, enrichment_id=item["enrichment_id"])
                    for item, prediction in zip(inputs, predictions)
                ]
                processed = repository.save_role_predictions(rows)
            return {"processed": processed}
        except Exception as exc:
            with connect() as connection:
                EnrichmentRepository(connection).fail_role_batch(
                    enrichment_ids,
                    str(exc),
                )
            raise

    @task
    def extract_skills(items):
        enrichment_ids = [item["enrichment_id"] for item in items]
        if not enrichment_ids:
            return {"processed": 0, "skills": 0}
        try:
            with connect() as connection:
                repository = EnrichmentRepository(connection)
                aliases = repository.list_active_skill_aliases()
                extractor = SkillExtractor(aliases)
                inputs = repository.get_pending_skill_inputs(enrichment_ids)
                predictions = [
                    {
                        "enrichment_id": item["enrichment_id"],
                        "matches": extractor.extract(
                            item["description"],
                            item["company_name"],
                        ),
                    }
                    for item in inputs
                ]
                processed = repository.save_skill_predictions(predictions)
            return {
                "processed": processed,
                "skills": sum(len(row["matches"]) for row in predictions),
            }
        except Exception as exc:
            with connect() as connection:
                EnrichmentRepository(connection).fail_skill_batch(
                    enrichment_ids,
                    str(exc),
                )
            raise

    @task(trigger_rule="all_done")
    def finalize_enrichment(items):
        enrichment_ids = [item["enrichment_id"] for item in items]
        with connect() as connection:
            finalized = EnrichmentRepository(
                connection
            ).finalize_enrichment_batch(enrichment_ids)
        return {"finalized": finalized}

    target_batches = select_targets()
    prepared_batches = prepare_enrichment.expand(history_ids=target_batches)
    role_results = classify_job_role.expand(items=prepared_batches)
    skill_results = extract_skills.expand(items=prepared_batches)
    finalized = finalize_enrichment.expand(items=prepared_batches)
    [role_results, skill_results] >> finalized


devcompass_job_enrichment()
