"""Relevance rules deciding which tournaments are surfaced in the app.

All matching is case-insensitive substring matching.
"""
from typing import Callable, Iterable

Record = dict


def _name(rec: Record) -> str:
    return str(rec.get("name") or "").lower()


def _tags(rec: Record) -> list:
    return [str(t).lower() for t in (rec.get("category_tags") or [])]


def _has_tag(rec: Record, needle: str) -> bool:
    return any(needle in tag for tag in _tags(rec))


def _tag_count(rec: Record, needle: str) -> int:
    return sum(1 for tag in _tags(rec) if needle in tag)


def _any_tag(rec: Record, needles: Iterable[str]) -> bool:
    return any(_has_tag(rec, n) for n in needles)


STAR_3_PLUS = ("3 star", "3.5 star", "4 star")
STAR_2_PLUS = ("2 star",) + STAR_3_PLUS

RULES: list = [
    ("U12 + Yonex", lambda r: "u12" in _name(r) and "yonex" in _name(r)),
    ("GU12 + Yonex", lambda r: "gu12" in _name(r) and "yonex" in _name(r)),
    ("GU14 + Yonex", lambda r: "gu14" in _name(r) and "yonex" in _name(r)),
    ("U14 + Yonex", lambda r: "u14" in _name(r) and "yonex" in _name(r)),
    ("Sobeys", lambda r: "sobeys" in _name(r)),
    ("Selection", lambda r: "selection" in _name(r)),
    ("Junior Open Series", lambda r: _has_tag(r, "junior open series")),
    ("4 Star", lambda r: _has_tag(r, "4 star") or "4 star" in _name(r) or "4-star" in _name(r)),
    ("Provincial x2", lambda r: _tag_count(r, "provincial") >= 2),
    ("National x2", lambda r: _tag_count(r, "national") >= 2),
    ("U12 Provincial Championships",
     lambda r: "u12" in _name(r) and "provincial championships" in _name(r)),
    ("U14 Provincial Championships",
     lambda r: "u14" in _name(r) and "provincial championships" in _name(r)),
    ("Junior Championships", lambda r: "junior" in _name(r) and "championships" in _name(r)),
    ("Team Championships", lambda r: "team championships" in _name(r)),
    ("Fischer", lambda r: "fischer" in _name(r)),
    ("U12 + 3 Star or better",
     lambda r: ("u12" in _name(r) or "gu12" in _name(r)) and _any_tag(r, STAR_3_PLUS)),
    ("U14 + 2 Star or better",
     lambda r: ("u14" in _name(r) or "gu14" in _name(r)) and _any_tag(r, STAR_2_PLUS)),
    ("U16 + 2 Star",
     lambda r: ("u16" in _name(r) or "gu16" in _name(r)) and _has_tag(r, "2 star")),
]


def matched_rules(rec: Record) -> list:
    return [label for label, test in RULES if test(rec)]


def is_relevant(rec: Record) -> bool:
    return any(test(rec) for _, test in RULES)
