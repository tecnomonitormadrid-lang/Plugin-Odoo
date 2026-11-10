import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


@dataclass
class PollerConfig:
    agora_base_url: str
    agora_closed_tickets_path: str
    agora_api_token: str
    connector_tickets_url: str
    poll_interval_seconds: int
    request_timeout_seconds: int
    state_file: Path
    dry_run: bool


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config() -> PollerConfig:
    return PollerConfig(
        agora_base_url=_env("AGORA_BASE_URL"),
        agora_closed_tickets_path=_env("AGORA_CLOSED_TICKETS_PATH", "/api/v1/tickets/closed"),
        agora_api_token=_env("AGORA_API_TOKEN"),
        connector_tickets_url=_env("CONNECTOR_TICKETS_URL", "http://localhost:8081/api/v1/tickets"),
        poll_interval_seconds=int(_env("AGORA_POLL_INTERVAL_SECONDS", "30")),
        request_timeout_seconds=int(_env("AGORA_REQUEST_TIMEOUT_SECONDS", "15")),
        state_file=Path(_env("AGORA_STATE_FILE", "./scripts/agora_poller_state.json")),
        dry_run=_env("AGORA_DRY_RUN", "false").lower() == "true",
    )


def load_since_cursor(state_file: Path) -> str:
    if not state_file.exists():
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    content = json.loads(state_file.read_text(encoding="utf-8"))
    return str(content.get("last_since", datetime.now(timezone.utc).isoformat()))


def save_since_cursor(state_file: Path, since_value: str) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_since": since_value}, indent=2), encoding="utf-8")


def fetch_closed_tickets(config: PollerConfig, since_value: str) -> list[dict[str, Any]]:
    endpoint = f"{config.agora_base_url.rstrip('/')}{config.agora_closed_tickets_path}"
    headers = {
        "Authorization": f"Bearer {config.agora_api_token}",
        "Accept": "application/json",
    }
    response = requests.get(
        endpoint,
        headers=headers,
        params={"since": since_value},
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()

    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        rows = payload["data"]
    else:
        rows = payload

    if not isinstance(rows, list):
        raise RuntimeError("Agora response format invalid: expected list or {'data': [...]}.")

    return rows


def map_agora_ticket_to_connector(agora_ticket: dict[str, Any]) -> dict[str, Any]:
    lines = agora_ticket.get("lines", [])
    payments = agora_ticket.get("payments", [])

    mapped_items = [
        {
            "product_sku": str(line.get("sku", line.get("product_code", "UNKNOWN"))),
            "quantity": float(line.get("qty", line.get("quantity", 0))),
            "unit_price": float(line.get("unit_price", line.get("price", 0))),
        }
        for line in lines
    ]

    mapped_payments = [
        {
            "method": str(payment.get("method", payment.get("type", "unknown"))),
            "amount": float(payment.get("amount", 0)),
        }
        for payment in payments
    ]

    return {
        "external_ticket_id": str(agora_ticket["id"]),
        "location_code": str(agora_ticket.get("store_code", "UNKNOWN")),
        "issued_at": str(agora_ticket.get("closed_at", agora_ticket.get("issued_at"))),
        "currency": str(agora_ticket.get("currency", "EUR")),
        "total_amount": float(agora_ticket.get("total", 0)),
        "items": mapped_items,
        "payments": mapped_payments,
    }


def publish_to_connector(config: PollerConfig, ticket_payload: dict[str, Any]) -> dict[str, Any]:
    if config.dry_run:
        return {"status": "dry_run", "external_ticket_id": ticket_payload["external_ticket_id"]}

    response = requests.post(
        config.connector_tickets_url,
        json=ticket_payload,
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def process_batch(config: PollerConfig) -> None:
    since_value = load_since_cursor(config.state_file)
    tickets = fetch_closed_tickets(config, since_value)

    if not tickets:
        print(f"[poller] no closed tickets since {since_value}")
        return

    max_closed_at = since_value
    print(f"[poller] fetched {len(tickets)} closed tickets")

    for ticket in tickets:
        payload = map_agora_ticket_to_connector(ticket)
        result = publish_to_connector(config, payload)
        ticket_id = payload["external_ticket_id"]
        print(f"[poller] published ticket={ticket_id} result={result.get('status', 'ok')}")

        ticket_closed_at = str(ticket.get("closed_at", since_value))
        if ticket_closed_at > max_closed_at:
            max_closed_at = ticket_closed_at

    save_since_cursor(config.state_file, max_closed_at)
    print(f"[poller] cursor updated to {max_closed_at}")


def run_forever(config: PollerConfig) -> None:
    print("[poller] started")
    print(f"[poller] dry_run={config.dry_run} interval={config.poll_interval_seconds}s")

    while True:
        try:
            process_batch(config)
        except Exception as exc:
            print(f"[poller] error: {exc}")
        time.sleep(config.poll_interval_seconds)


def main() -> None:
    config = load_config()
    run_forever(config)


if __name__ == "__main__":
    main()
