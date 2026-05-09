from platform_wallet.service import sanitize_ledger_entry, wallet_summary


def test_wallet_summary_exposes_balance_locked_and_available_demo_credit_copy():
    summary = wallet_summary("u1", {"balance": 1000, "locked_balance": 250})

    assert summary["user_id"] == "u1"
    assert summary["balance"] == 1000
    assert summary["locked"] == 250
    assert summary["locked_balance"] == 250
    assert summary["available_balance"] == 1000
    assert summary["currency_type"] == "internal_demo_credit"
    assert "Live deposits" in summary["sandbox_notice"]


def test_wallet_summary_supports_legacy_locked_alias():
    summary = wallet_summary("u1", {"balance": 900, "locked": 100})

    assert summary["locked"] == 100
    assert summary["locked_balance"] == 100


def test_ledger_entry_sanitizes_game_lock_row():
    entry = sanitize_ledger_entry({
        "id": "tx1",
        "source_module": "target",
        "ref_id": "tbl1",
        "reason": "target_join_lock",
        "amount": -100,
        "balance_after": 900,
        "created_at": "2026-05-10T00:00:00Z",
        "status": "POSTED",
    })

    assert entry == {
        "id": "tx1",
        "source_module": "target",
        "source_label": "Target",
        "source_id": "tbl1",
        "reason": "target_join_lock",
        "reason_label": "join lock",
        "amount": -100,
        "balance_before": 1000,
        "balance_after": 900,
        "locked_before": None,
        "locked_after": None,
        "created_at": "2026-05-10T00:00:00Z",
        "status": "POSTED",
    }


def test_ledger_entry_infers_legacy_signup_bonus_as_admin():
    entry = sanitize_ledger_entry({
        "id": "tx_signup",
        "reason": "SIGNUP_BONUS",
        "amount": 10000,
        "balance_after": 10000,
    })

    assert entry["source_module"] == "admin"
    assert entry["source_label"] == "Admin"
    assert entry["reason_label"] == "signup bonus"
    assert entry["balance_before"] == 0


def test_ledger_entry_labels_all_known_modules_and_reasons():
    samples = [
        ("diceget", "diceget_cancel_unlock", "Diceget", "cancel unlock"),
        ("flipget", "flipget_win_payout", "Flipget", "win payout"),
        ("tmarget", "tmarget_refund", "Tmarget", "tmarget refund"),
        ("payment", "sandbox_deposit", "Payment", "sandbox deposit"),
        ("admin", "admin_credit", "Admin", "admin credit"),
    ]

    for source_module, reason, source_label, reason_label in samples:
        entry = sanitize_ledger_entry({
            "id": f"tx_{source_module}",
            "source_module": source_module,
            "reason": reason,
            "amount": 0,
        })
        assert entry["source_label"] == source_label
        assert entry["reason_label"] == reason_label
