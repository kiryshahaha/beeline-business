"""Seed only an isolated synthetic_<seed> schema in TEST_DATABASE_URL (*_test)."""

import argparse
import json
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.security import hash_password
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from generate_synthetic import generate_dataset


def validate_database_url(value: str):
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL должен указывать на PostgreSQL с именем БД *_test")
    return url


def seed(*, database_url: str, seed: int = 42, tickets=1500, workers=120, days=7, reset=False):
    url = validate_database_url(database_url)
    if not 0 <= seed <= 2_147_483_647:
        raise ValueError("seed должен быть неотрицательным int32")
    schema = f"synthetic_{seed}"
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            if reset:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(CreateSchema(schema, if_not_exists=True))
    finally:
        admin.dispose()
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        config = Config("alembic.ini")
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        data = generate_dataset(seed=seed, tickets=tickets, workers=workers, days=days)
        with Session(engine) as session:
            result = import_data(session, parse_file(serialize(data, "csv"), "data.zip"))
            # Published test-only password; never applied outside *_test / synthetic_<seed>.
            password_hash = hash_password(os.getenv("SYNTHETIC_TEST_PASSWORD", "SyntheticOnly123!"))
            with session.begin():
                for user_id in result["id_map"]["users"].values():
                    session.execute(
                        text("UPDATE users SET password_hash=:hash WHERE id=:id"),
                        {"hash": password_hash, "id": user_id},
                    )
        return {
            "schema": schema,
            "counts": result["counts"],
            "duplicate": result["duplicate"],
            "observer_username": f"synthetic_{seed}_observer_1",
        }
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tickets", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=120)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Удалить и пересоздать только synthetic_<seed> в *_test",
    )
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("Задайте TEST_DATABASE_URL (рабочий DATABASE_URL не используется)")
    print(json.dumps(seed(database_url=url, **vars(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
