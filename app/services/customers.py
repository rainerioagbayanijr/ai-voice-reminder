"""Validate CSV rows independently and suppress duplicates within one test batch."""

from typing import Any

from pydantic import ValidationError

from app.models import Customer


def prepare_customer_batch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    seen = set()
    for index, row in enumerate(rows):
        item: dict[str, Any] = {"row_index": index + 1}
        try:
            customer = Customer.model_validate(row)
        except ValidationError:
            results.append({**item, "status": "skipped", "reason": "invalid_customer"})
            continue
        item["customer_id"] = customer.customer_id
        if not customer.reminder_eligible:
            results.append({**item, "status": "skipped", "reason": "ineligible"})
            continue
        key = (customer.customer_id, customer.due_date)
        if key in seen:
            results.append({**item, "status": "skipped", "reason": "duplicate_in_batch"})
            continue
        seen.add(key)
        results.append(
            {
                **item,
                "status": "eligible",
                "voice_request": customer.voice_request().model_dump(mode="json"),
            }
        )
    return results
