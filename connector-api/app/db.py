from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_database_url


class Base(DeclarativeBase):
    pass


def _build_engine():
    database_url = get_database_url()
    connect_args: dict[str, bool] = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import TicketRecord

    _ = TicketRecord
    Base.metadata.create_all(bind=engine)
    _ensure_ticket_columns()


def _ensure_ticket_columns() -> None:
    inspector = inspect(engine)
    if "tpv_tickets" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("tpv_tickets")}
    statements: list[str] = []

    if "next_retry_at" not in columns:
        statements.append("ALTER TABLE tpv_tickets ADD COLUMN next_retry_at TIMESTAMP NULL")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
