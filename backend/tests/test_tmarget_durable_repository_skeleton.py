import importlib
import inspect

import pytest

from tmarget.durable_repository import DurableTmargetRepository, TmargetDurableRepository
from tmarget.repository import InMemoryTmargetRepository
from tmarget.service import TmargetService


EXPECTED_PUBLIC_METHODS = {
    "create_market",
    "get_market",
    "get_market_by_slug",
    "list_markets",
    "update_market",
    "create_trade",
    "list_market_trades",
    "get_user_positions",
    "list_market_positions",
    "get_position",
    "upsert_position",
    "get_pool",
    "update_pool",
    "record_settlement",
    "has_settlement",
    "record_refund",
    "has_refund",
    "record_admin_action",
    "list_admin_actions",
    "record_status_history",
    "list_status_history",
}


def test_durable_repository_skeleton_class_exists():
    assert DurableTmargetRepository is TmargetDurableRepository
    public_methods = {
        name
        for name, value in inspect.getmembers(DurableTmargetRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert EXPECTED_PUBLIC_METHODS.issubset(public_methods)


def test_importing_durable_repository_does_not_require_database_packages():
    module = importlib.import_module("tmarget.durable_repository")
    assert module.DurableTmargetRepository is DurableTmargetRepository


def test_tmarget_service_default_repository_remains_in_memory():
    service = TmargetService()
    assert isinstance(service.repo, InMemoryTmargetRepository)
    assert not isinstance(service.repo, DurableTmargetRepository)


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs"),
    [
        ("create_market", (None,), {}),
        ("get_market", ("market-id",), {}),
        ("get_market_by_slug", ("slug",), {}),
        ("list_markets", (), {}),
        ("update_market", (None,), {}),
        ("create_trade", (None,), {}),
        ("list_market_trades", ("market-id",), {}),
        ("get_user_positions", ("user-id",), {}),
        ("list_market_positions", ("market-id",), {}),
        ("get_position", ("user-id", "market-id", "yes"), {}),
        ("upsert_position", (None,), {}),
        ("get_pool", ("market-id",), {}),
        ("update_pool", ("market-id", None), {}),
        ("record_settlement", ("market-id", "user-id", "yes", 100, "settlement-key"), {}),
        ("has_settlement", ("settlement-key",), {}),
        ("record_refund", ("market-id", "user-id", "yes", 100, "refund-key"), {}),
        ("has_refund", ("refund-key",), {}),
        ("record_admin_action", ("open_market", "market-id", "admin-id"), {}),
        ("list_admin_actions", (), {}),
        (
            "record_status_history",
            (),
            {
                "market_id": "market-id",
                "from_status": "draft",
                "to_status": "open",
                "changed_by": "admin-id",
                "reason": "test",
            },
        ),
        ("list_status_history", ("market-id",), {}),
    ],
)
def test_durable_repository_methods_fail_closed(method_name, args, kwargs):
    repo = DurableTmargetRepository()
    with pytest.raises(NotImplementedError, match="inactive skeleton"):
        getattr(repo, method_name)(*args, **kwargs)
