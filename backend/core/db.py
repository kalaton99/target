"""MongoDB client + collection accessors."""
from motor.motor_asyncio import AsyncIOMotorClient
from .config import MONGO_URL, DB_NAME

_client = AsyncIOMotorClient(MONGO_URL)
db = _client[DB_NAME]

# Collections
users = db["users"]
wallets = db["wallets"]
transactions = db["transactions"]
idempotency_keys = db["idempotency_keys"]
tables = db["tables"]
hands = db["hands"]
hand_actions = db["hand_actions"]
hand_participants = db["hand_participants"]
rng_seeds = db["rng_seeds"]
audit_log = db["audit_log"]


async def ensure_indexes() -> None:
    """Idempotent index creation. Called on startup."""
    await users.create_index("email", unique=True)
    await users.create_index("username", unique=True)
    await wallets.create_index("user_id", unique=True)
    await transactions.create_index([("user_id", 1), ("created_at", -1)])
    await transactions.create_index("journal_id")
    await idempotency_keys.create_index(
        [("user_id", 1), ("scope", 1), ("client_action_id", 1)],
        unique=True,
    )
    await idempotency_keys.create_index("expires_at", expireAfterSeconds=0)
    await tables.create_index("status")
    await hands.create_index([("table_id", 1), ("hand_number", 1)], unique=True)
    await hand_actions.create_index([("hand_id", 1), ("seq", 1)], unique=True)
    await hand_actions.create_index([("table_id", 1), ("created_at", -1)])
    await hand_participants.create_index([("hand_id", 1), ("user_id", 1)], unique=True)
    await rng_seeds.create_index("hand_id", unique=True)
    await audit_log.create_index([("user_id", 1), ("created_at", -1)])
    await audit_log.create_index([("severity", 1), ("created_at", -1)])


def close_client() -> None:
    _client.close()
