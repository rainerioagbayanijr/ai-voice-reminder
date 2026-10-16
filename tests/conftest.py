import pytest

from app.core.config import Settings


@pytest.fixture
def settings():
    return Settings(reminder_api_key="test-key-" + "x" * 32, _env_file=None)


@pytest.fixture
def customer():
    return {
        "customer_id": "CUST001",
        "first_name": "Juan",
        "email": "juan@example.com",
        "phone": "+639171111111",
        "bank_name": "Example Fictional Bank",
        "agent_name": "Alex",
        "due_date": "2026-11-15",
        "reminder_eligible": "true",
    }


@pytest.fixture
def voice(customer):
    return {
        key: value
        for key, value in customer.items()
        if key not in {"email", "phone", "reminder_eligible"}
    }
