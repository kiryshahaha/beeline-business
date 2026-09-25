import sqlalchemy

engine = sqlalchemy.create_engine(
    "postgresql+psycopg://postgres:postgres@localhost:5432/postgres", isolation_level="AUTOCOMMIT"
)
with engine.connect() as conn:
    res = conn.execute(
        sqlalchemy.text("SELECT 1 FROM pg_database WHERE datname='beeline_test'")
    ).fetchone()
    if not res:
        conn.execute(sqlalchemy.text("CREATE DATABASE beeline_test"))
        print("Database created.")
    else:
        print("Database already exists.")
