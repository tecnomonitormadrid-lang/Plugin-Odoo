import os


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://odoo:odoo_dev_password_change_me@db:5432/postgres",
    )


def get_odoo_base_url() -> str:
    return os.getenv("ODOO_BASE_URL", "http://odoo:8069")


def get_odoo_push_path() -> str:
    return os.getenv("ODOO_PUSH_PATH", "/connector/tickets")


def get_sync_batch_size() -> int:
    return int(os.getenv("SYNC_BATCH_SIZE", "50"))


def get_sync_timeout_seconds() -> int:
    return int(os.getenv("SYNC_TIMEOUT_SECONDS", "10"))


def get_sync_max_retries() -> int:
    return int(os.getenv("SYNC_MAX_RETRIES", "5"))


def get_sync_backoff_base_seconds() -> int:
    return int(os.getenv("SYNC_BACKOFF_BASE_SECONDS", "30"))


def get_sync_backoff_max_seconds() -> int:
    return int(os.getenv("SYNC_BACKOFF_MAX_SECONDS", "1800"))
