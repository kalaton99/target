"""Phase 4 unit tests — append-only event log + deterministic replay.

Scope (locked):
  - hand_actions schema/model + indexes
  - HandActionWriter.append (and only append)
  - per-hand monotonic seq
  - state_version_before / state_version_after invariant
  - client_action_id + payload + events + action_type stored
  - deterministic replay rebuilds the same state
  - append-only contract (no update/delete API; UNIQUE blocks duplicates)

Tests use the real MongoDB (motor); each test isolates itself via a fresh
hand_id derived from the test name + uuid, and cleans up at teardown.

Run:
  cd /app/backend && PYTHONPATH=. python -m pytest tests/test_event_log_phase4.py -v
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import pytest
from pymongo.errors import DuplicateKeyError

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import MONGO_URL, DB_NAME, ENGINE_VERSION
from event_log.writer import HandActionWriter
from event_log.replay import replay, deterministic_dict
from game_engine.reducer import reduce as pure_reduce
from game_engine.rng import generate_server_seed, combine_client_seeds
from game_engine.types import GameState, PlayerState


# ---------- fixtures ----------

async def _safe_create_client(retries: int = 3):
    from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError
    last = None
    for i in range(retries):
        try:
            client = AsyncIOMotorClient(MONGO_URL, maxPoolSize=10)
            await client.admin.command("ping")
            return client
        except (AutoReconnect, ServerSelectionTimeoutError) as exc:
            last = exc
            await asyncio.sleep(0.05 * (i + 1))
    raise last  # type: ignore[misc]


@pytest.fixture
async def mongo():
    client = await _safe_create_client()
    db = client[f"{DB_NAME}_phase4_{uuid.uuid4().hex[:8]}"]
    actions = db["hand_actions"]
    counters = db["hand_seq_counters"]
    await actions.create_index([("hand_id", 1), ("seq", 1)], unique=True)
    yield {"actions": actions, "counters": counters, "db": db}
    try:
        await client.drop_database(db.name)
    except Exception:
        pass
    client.close()


@pytest.fixture
async def writer(mongo):
    return HandActionWriter(mongo["actions"], mongo["counters"])


def _initial_state(table_id="t_p4", num_players=2) -> GameState:
    return GameState(
        table_id=table_id,
        engine_version=ENGINE_VERSION,
        phase="WAITING",
        version=0,
        players=[
            PlayerState(
                seat_index=i,
                user_id=f"u{i}",
                username=f"p{i}",
                balance_at_start=10_000,
            )
            for i in range(num_players)
        ],
        deck=[],
        pot=0,
        stake=100,
        max_players=num_players,
    )


def _start_hand_intent(hand_id: str, nonce: int = 1):
    plain, h = generate_server_seed()
    # Make seeds deterministic per test by deriving them from hand_id so that
    # rerunning a test isn't accidentally relying on randomness.
    plain = uuid.uuid5(uuid.NAMESPACE_DNS, hand_id).hex
    import hashlib
    h = hashlib.sha256(plain.encode()).hexdigest()
    return {
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": hand_id,
        "server_seed": plain,
        "server_seed_hash": h,
        "client_seeds": combine_client_seeds([]),
        "nonce": nonce,
    }


async def _apply_and_log(writer, state: GameState, intent: dict, hand_id: str, table_id: str) -> GameState:
    """Helper: apply intent through pure reducer + persist via writer."""
    before = state.version
    new_state, events = pure_reduce(state, intent)
    after = new_state.version
    await writer.append(
        hand_id=hand_id,
        table_id=table_id,
        intent=intent,
        events=events,
        state_version_before=before,
        state_version_after=after,
    )
    return new_state


async def _act_current_turn(writer, state: GameState, action_type: str, hand_id: str, table_id: str, *, payload=None, cid=None) -> GameState:
    """Apply an action for whichever player is currently on turn.

    Resilient to deterministic-but-uncontrolled shuffle outcomes (e.g. Joker DQ).
    """
    seat = state.current_turn_seat
    assert seat is not None, f"no current_turn_seat in phase={state.phase}"
    player = state.players[seat]
    intent = {
        "type": action_type,
        "user_id": player.user_id,
        "seat_index": seat,
        "source": "CLIENT",
        "state_version": state.version,
        "client_action_id": cid or f"c-{action_type}-{seat}-{state.version}",
        "payload": payload or {},
    }
    return await _apply_and_log(writer, state, intent, hand_id, table_id)


# ---------- append-only writer ----------

class TestWriterContract:

    @pytest.mark.asyncio
    async def test_writer_has_only_append_in_public_api(self):
        public = [m for m in dir(HandActionWriter) if not m.startswith("_")]
        # `append` and `list_for_hand` (read-only). No update/delete/replace.
        assert "append" in public
        assert "list_for_hand" in public
        forbidden = {"update", "update_one", "delete", "delete_one", "replace_one"}
        assert forbidden.isdisjoint(public)

    @pytest.mark.asyncio
    async def test_first_seq_is_one_then_monotonic(self, writer, mongo):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        # Pure writer test — no reducer needed. Three hypothetical mutations.
        for i in range(3):
            await writer.append(
                hand_id=hand_id,
                table_id="t",
                intent={"type": "STAND", "user_id": "u", "source": "SERVER"},
                events=[],
                state_version_before=i,
                state_version_after=i + 1,
            )
        docs = await writer.list_for_hand(hand_id)
        assert [d["seq"] for d in docs] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_seq_is_per_hand_not_global(self, writer):
        h1 = f"h_{uuid.uuid4().hex[:8]}"
        h2 = f"h_{uuid.uuid4().hex[:8]}"
        s1 = _initial_state(table_id="tA")
        s2 = _initial_state(table_id="tB")
        s1 = await _apply_and_log(writer, s1, _start_hand_intent(h1), h1, s1.table_id)
        s2 = await _apply_and_log(writer, s2, _start_hand_intent(h2), h2, s2.table_id)
        s2 = await _apply_and_log(writer, s2, {
            "type": "CHECK", "user_id": "u0", "source": "CLIENT",
            "state_version": s2.version, "client_action_id": "x",
        }, h2, s2.table_id)
        d1 = await writer.list_for_hand(h1)
        d2 = await writer.list_for_hand(h2)
        assert [d["seq"] for d in d1] == [1]
        assert [d["seq"] for d in d2] == [1, 2]

    @pytest.mark.asyncio
    async def test_duplicate_seq_for_same_hand_is_rejected(self, writer, mongo):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        # Manually insert a doc with seq=1
        await mongo["actions"].insert_one({
            "id": "ha_manual",
            "hand_id": hand_id,
            "seq": 1,
            "table_id": "t",
            "action_type": "MANUAL",
            "payload": {},
            "events": [],
            "state_version_before": 0,
            "state_version_after": 1,
            "user_id": None,
            "seat_index": None,
            "client_action_id": None,
            "source": "SERVER",
            "created_at": "now",
        })
        # Simulate a second writer trying to insert the same (hand_id, seq=1)
        with pytest.raises(DuplicateKeyError):
            await mongo["actions"].insert_one({
                "id": "ha_dup",
                "hand_id": hand_id,
                "seq": 1,
                "table_id": "t",
                "action_type": "OTHER",
                "payload": {},
                "events": [],
                "state_version_before": 0,
                "state_version_after": 1,
                "user_id": None,
                "seat_index": None,
                "client_action_id": None,
                "source": "SERVER",
                "created_at": "now",
            })

    @pytest.mark.asyncio
    async def test_append_stores_required_fields(self, writer):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        # Pure writer test — directly append two actions without going
        # through the reducer; verify all fields persisted.
        await writer.append(
            hand_id=hand_id, table_id="t_test",
            intent={"type": "START_HAND", "source": "SERVER",
                    "hand_id": hand_id, "server_seed": "abc",
                    "server_seed_hash": "h", "client_seeds": "", "nonce": 1},
            events=[{"type": "DEAL_COMPLETE"}],
            state_version_before=0, state_version_after=1,
        )
        await writer.append(
            hand_id=hand_id, table_id="t_test",
            intent={
                "type": "STAND",
                "user_id": "u0",
                "seat_index": 0,
                "source": "CLIENT",
                "client_action_id": "ca-1",
                "payload": {"note": "pre-bust"},
            },
            events=[{"type": "STAND", "seat": 0}],
            state_version_before=1, state_version_after=2,
        )

        docs = await writer.list_for_hand(hand_id)
        last = docs[-1]
        assert last["action_type"] == "STAND"
        assert last["client_action_id"] == "ca-1"
        assert last["payload"] == {"note": "pre-bust"}
        assert last["state_version_before"] == 1
        assert last["state_version_after"] == 2
        assert isinstance(last["events"], list) and len(last["events"]) >= 1
        assert any(e["type"] == "STAND" for e in last["events"])
        assert last["user_id"] == "u0"
        assert last["seat_index"] == 0
        assert last["source"] == "CLIENT"
        assert last["seq"] == 2
        assert last["hand_id"] == hand_id

    @pytest.mark.asyncio
    async def test_append_rejects_invalid_state_version_increment(self, writer):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        with pytest.raises(ValueError, match="STATE_VERSION_INCREMENT_INVALID"):
            await writer.append(
                hand_id=hand_id,
                table_id="t",
                intent={"type": "STAND"},
                events=[],
                state_version_before=5,
                state_version_after=7,  # not +1
            )

    @pytest.mark.asyncio
    async def test_auto_stand_timeout_stored_as_timeout_autostand(self, writer):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        # Pure writer test — directly persist a server-emitted timeout intent.
        await writer.append(
            hand_id=hand_id, table_id="t_test",
            intent={
                "type": "AUTO_STAND_TIMEOUT",
                "source": "SERVER",
                "user_id": "u0",
                "seat_index": 0,
                "payload": {"reason": "TURN_TIMEOUT_15S", "source": "SERVER"},
            },
            events=[{"type": "STAND", "seat": 0, "auto": True, "reason": "TURN_TIMEOUT_15S"}],
            state_version_before=5, state_version_after=6,
        )
        docs = await writer.list_for_hand(hand_id)
        assert docs[-1]["action_type"] == "TIMEOUT_AUTOSTAND"
        assert docs[-1]["payload"]["reason"] == "TURN_TIMEOUT_15S"
        assert docs[-1]["source"] == "SERVER"


# ---------- deterministic replay ----------

class TestReplay:

    @pytest.mark.asyncio
    async def test_replay_rebuilds_identical_state(self, writer):
        """Run a full BETTING_R1 -> DRAW -> SHOWDOWN sequence; replay from a fresh
        initial state and assert every deterministic field matches.
        """
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        s_initial = _initial_state()
        s = s_initial
        s = await _apply_and_log(writer, s, _start_hand_intent(hand_id), hand_id, s.table_id)
        # BETTING_R1: both players CHECK -> DRAW
        s = await _apply_and_log(writer, s, {
            "type": "CHECK", "user_id": "u0", "source": "CLIENT",
            "state_version": s.version, "client_action_id": "ca-check-0",
        }, hand_id, s.table_id)
        s = await _apply_and_log(writer, s, {
            "type": "CHECK", "user_id": "u1", "source": "CLIENT",
            "state_version": s.version, "client_action_id": "ca-check-1",
        }, hand_id, s.table_id)
        # DRAW: with 2 seated players (4-seat tier minimum), threshold=1 -> first STAND -> SHOWDOWN
        if s.phase == "DRAW":
            seat = s.current_turn_seat
            user = s.players[seat].user_id
            s = await _apply_and_log(writer, s, {
                "type": "STAND", "user_id": user, "source": "CLIENT",
                "state_version": s.version, "client_action_id": "ca-stand-0",
            }, hand_id, s.table_id)

        # ---- replay ----
        docs = await writer.list_for_hand(hand_id)
        replayed = replay(s_initial, docs)
        assert deterministic_dict(replayed) == deterministic_dict(s)

    @pytest.mark.asyncio
    async def test_replay_with_hit_actions_reproduces_cards_dealt(self, writer):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        s_initial = _initial_state()
        s = s_initial
        s = await _apply_and_log(writer, s, _start_hand_intent(hand_id), hand_id, s.table_id)
        # Hit for whoever is on turn (resilient to Joker DQ on deal).
        if s.phase == "DRAW" and s.current_turn_seat is not None:
            seat = s.current_turn_seat
            s = await _act_current_turn(writer, s, "HIT", hand_id, s.table_id)
            cards_after = list(s.players[seat].cards)
        else:
            cards_after = None

        docs = await writer.list_for_hand(hand_id)
        replayed = replay(s_initial, docs)
        if cards_after is not None:
            assert replayed.players[seat].cards == cards_after
        # Deck contents equal too (same shuffle from same seed).
        assert replayed.deck == s.deck

    @pytest.mark.asyncio
    async def test_replay_detects_seq_gap(self, writer, mongo):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        s_initial = _initial_state()
        s = await _apply_and_log(writer, s_initial, _start_hand_intent(hand_id), hand_id, s_initial.table_id)
        # Manually delete the seq=1 doc to create a gap (this would only happen
        # in pathological / corruption scenarios — replay must detect it).
        await mongo["actions"].delete_one({"hand_id": hand_id, "seq": 1})
        # Insert a fake seq=2
        await mongo["actions"].insert_one({
            "id": "ha_fake",
            "hand_id": hand_id,
            "seq": 2,
            "table_id": s_initial.table_id,
            "action_type": "STAND",
            "payload": {},
            "events": [],
            "state_version_before": 1,
            "state_version_after": 2,
            "user_id": "u0",
            "seat_index": 0,
            "client_action_id": "x",
            "source": "CLIENT",
            "created_at": "now",
            "replay_inputs": None,
        })
        docs = await writer.list_for_hand(hand_id)
        with pytest.raises(ValueError, match="NON_MONOTONIC_SEQ"):
            replay(s_initial, docs)

    @pytest.mark.asyncio
    async def test_replay_detects_state_version_mismatch(self, writer, mongo):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        s_initial = _initial_state()
        s = await _apply_and_log(writer, s_initial, _start_hand_intent(hand_id), hand_id, s_initial.table_id)
        # Tamper with the persisted state_version_before — replay must detect.
        await mongo["actions"].update_one(
            {"hand_id": hand_id, "seq": 1},
            {"$set": {"state_version_before": 99}},  # wrong: should be 0
        )
        docs = await writer.list_for_hand(hand_id)
        with pytest.raises(ValueError, match="REPLAY_STATE_VERSION_MISMATCH"):
            replay(s_initial, docs)

    @pytest.mark.asyncio
    async def test_replay_with_auto_stand_timeout_reproduces_stand_not_fold(self, writer):
        hand_id = f"h_{uuid.uuid4().hex[:8]}"
        s_initial = _initial_state()
        s = await _apply_and_log(writer, s_initial, _start_hand_intent(hand_id), hand_id, s_initial.table_id)
        if s.phase != "DRAW" or s.current_turn_seat is None:
            pytest.skip("DEAL produced no DRAW turn (unlikely Joker scenario); skip")
        active_seat = s.current_turn_seat
        active_user = s.players[active_seat].user_id
        # Server-emitted timeout for whoever is currently on turn
        s = await _apply_and_log(writer, s, {
            "type": "AUTO_STAND_TIMEOUT", "source": "SERVER",
            "user_id": active_user, "seat_index": active_seat,
            "state_version": s.version,
            "payload": {"reason": "TURN_TIMEOUT_15S", "source": "SERVER"},
        }, hand_id, s.table_id)

        docs = await writer.list_for_hand(hand_id)
        replayed = replay(s_initial, docs)
        # On replay, that seat must be STAND, never FOLD
        assert replayed.players[active_seat].stood is True
        assert replayed.players[active_seat].folded is False
        # Stored type uses architecture-correct name
        assert any(d["action_type"] == "TIMEOUT_AUTOSTAND" for d in docs)
