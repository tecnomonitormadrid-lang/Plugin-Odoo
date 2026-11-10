import httpx

from app.config import get_odoo_base_url, get_odoo_push_path, get_sync_timeout_seconds


class OdooSyncError(Exception):
    pass


def push_ticket(payload: dict) -> None:
    base_url = get_odoo_base_url().rstrip("/")
    push_path = get_odoo_push_path()
    if not push_path.startswith("/"):
        push_path = f"/{push_path}"

    target_url = f"{base_url}{push_path}"
    timeout_seconds = get_sync_timeout_seconds()

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(target_url, json=payload)
    except httpx.HTTPError as exc:
        raise OdooSyncError(f"network error: {exc}") from exc

    if response.status_code >= 300:
        raise OdooSyncError(f"odoo response {response.status_code}: {response.text[:250]}")
