"""Card model. Standard 52 + 2 Jokers."""
from dataclasses import dataclass

SUITS = ["S", "H", "D", "C"]  # Spades, Hearts, Diamonds, Clubs
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


@dataclass(frozen=True)
class Card:
    rank: str          # A, 2..10, J, Q, K, JOKER
    suit: str          # S, H, D, C, * (joker)

    @property
    def code(self) -> str:
        if self.rank == "JOKER":
            return "JK"
        return f"{self.rank}{self.suit}"

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit, "code": self.code}

    @classmethod
    def from_code(cls, code: str) -> "Card":
        if code == "JK":
            return cls("JOKER", "*")
        if code.startswith("10"):
            return cls("10", code[2])
        return cls(code[0], code[1])
