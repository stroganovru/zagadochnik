# -*- coding: utf-8 -*-
"""Выбор загадок: без повторов в уровне, пока круг не закрыт."""

from __future__ import annotations

import random
from typing import Any

from game_data import LEVELS, RIDDLES


def get_riddle(rid: int) -> dict | None:
    for r in RIDDLES:
        if r["id"] == rid:
            return r
    return None


def riddles_by_level(level: str) -> list[dict]:
    return [r for r in RIDDLES if r["level"] == level]


def level_ids(level: str) -> set[int]:
    return {r["id"] for r in riddles_by_level(level)}


RIDDLE_LEVEL = {r["id"]: r["level"] for r in RIDDLES}


def normalize_seen(seen: Any) -> dict[str, list[int]]:
    """seen: dict по уровню или старый список id → {easy/medium/hard: [id,...]}."""
    buckets: dict[str, list[int]] = {"easy": [], "medium": [], "hard": []}

    def add(lv: str | None, i: int) -> None:
        if lv not in buckets:
            lv = RIDDLE_LEVEL.get(i)
        if lv not in buckets:
            return
        if i not in buckets[lv]:
            buckets[lv].append(i)

    if isinstance(seen, dict):
        for lv in buckets:
            for i in seen.get(lv) or []:
                add(lv, int(i))
        for i in seen.get("_legacy") or []:
            add(None, int(i))
    elif seen:
        for i in seen:
            add(None, int(i))
    return buckets


def _seen_ids(seen: Any, level: str) -> list[int]:
    return list(normalize_seen(seen).get(level) or [])


def pick_random_riddle(level: str, seen: Any) -> tuple[dict | None, bool, list[int]]:
    """
    Возвращает (задача, круг_закрыт, seen_этого_уровня_уже_без_новой).
    Если все задачи уровня показаны — сбрасывает круг этого уровня и ставит wrapped=True.
    """
    all_level = riddles_by_level(level)
    ids = {r["id"] for r in all_level}
    shown = [i for i in _seen_ids(seen, level) if i in ids]
    pool = [r for r in all_level if r["id"] not in shown]
    wrapped = False
    if not pool:
        shown = []
        pool = all_level
        wrapped = True
    if not pool:
        return None, False, shown
    r = random.choice(pool)
    return r, wrapped, shown


def remaining_in_round(level: str, shown: list[int]) -> int:
    ids = level_ids(level)
    return max(0, len(ids) - len({i for i in shown if i in ids}))


def level_label(level: str) -> str:
    return LEVELS.get(level, level)


def counts() -> dict[str, int]:
    out = {k: 0 for k in LEVELS}
    for r in RIDDLES:
        out[r["level"]] = out.get(r["level"], 0) + 1
    return out
