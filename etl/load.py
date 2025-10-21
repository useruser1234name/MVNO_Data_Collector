"""Database loading helpers for MVNO plan datasets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine


@dataclass(slots=True)
class LoadConfig:
    dsn: str
    staging_table: str = "stg_mvno_plans_raw"
    mart_table: str = "mart_mvno_plans"


class PlanLoader:
    def __init__(self, config: LoadConfig) -> None:
        self.config = config
        self.engine: Engine = create_engine(config.dsn)
        self.metadata = MetaData()

    def load_to_staging(self, records: Iterable[Mapping]) -> None:
        table = Table(self.config.staging_table, self.metadata, autoload_with=self.engine)
        with self.engine.begin() as conn:
            conn.execute(table.insert(), list(records))

    def upsert_to_mart(self, records: Iterable[Mapping], conflict_keys: list[str]) -> None:
        mart_table = Table(self.config.mart_table, self.metadata, autoload_with=self.engine)
        stmt = insert(mart_table).values(list(records))
        update_cols = {col.name: col for col in stmt.excluded if col.name not in conflict_keys}
        upsert_stmt = stmt.on_conflict_do_update(index_elements=conflict_keys, set_=update_cols)
        with self.engine.begin() as conn:
            conn.execute(upsert_stmt)
