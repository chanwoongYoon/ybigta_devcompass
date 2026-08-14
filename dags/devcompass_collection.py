import os
from datetime import datetime, timedelta, timezone

import psycopg
from airflow.sdk import dag, get_current_context, task
from airflow.utils.trigger_rule import TriggerRule

from devcompass.models import Board
from devcompass.service import collect_board
from devcompass.storage import (
    BoardRepository,
    CollectionRunRepository,
    JobPostingRepository,
)


DEVCOMPASS_DSN = os.environ.get(
    "DEVCOMPASS_DSN", "postgresql://localhost/devcompass"
)


def connect():
    return psycopg.connect(DEVCOMPASS_DSN)


@dag(
    dag_id="devcompass_public_ats_collection",
    schedule="0 6 * * *",
    start_date=datetime(2026, 8, 12, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "devcompass",
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["devcompass", "ats", "postgresql"],
)
def devcompass_public_ats_collection():
    @task
    def start_collection_run():
        context = get_current_context()
        run_id = context["run_id"]
        with connect() as connection:
            boards = BoardRepository(connection).list_enabled()
            CollectionRunRepository(connection).start(run_id, len(boards))
        return run_id

    @task
    def get_enabled_boards(collection_run_id):
        with connect() as connection:
            boards = BoardRepository(connection).list_enabled()
        return [
            {
                "run_id": collection_run_id,
                "board_id": board.board_id,
                "company_name": board.company_name,
                "ats_source": board.ats_source,
                "board_slug": board.board_slug,
            }
            for board in boards
        ]

    @task
    def collect_and_load_board(item):
        board = Board(
            board_id=item["board_id"],
            company_name=item["company_name"],
            ats_source=item["ats_source"],
            board_slug=item["board_slug"],
        )
        with connect() as connection:
            summary = collect_board(
                run_id=item["run_id"],
                board=board,
                repository=JobPostingRepository(connection),
            )
        return {
            "company": board.company_name,
            "new": summary.new,
            "changed": summary.changed,
            "unchanged": summary.unchanged,
            "closed": summary.closed,
        }

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def finalize_collection_run(collection_run_id):
        with connect() as connection:
            CollectionRunRepository(connection).finalize(collection_run_id)

    run_id = start_collection_run()
    boards = get_enabled_boards(run_id)
    mapped_collection = collect_and_load_board.expand(item=boards)
    finalized = finalize_collection_run(run_id)
    mapped_collection >> finalized


devcompass_public_ats_collection()
