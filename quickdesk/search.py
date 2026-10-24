"""Search and ranking of commands.

The algorithm is intentionally simple so it is easy to follow:

1. The query is split into words (tokens). Every token must match
   something in the command, otherwise the command is not shown.
2. Each token is compared with the words of the name, description and
   category. An exact word scores highest, then a word prefix, then a
   substring, then a "close enough" spelling (to tolerate typos).
3. Matches in the name are worth more than matches in the description
   or category. A name that equals or starts with the whole query gets
   an extra bonus.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from .commands import Command

# How much a match in each field is worth.
NAME_WEIGHT = 1.0
DESCRIPTION_WEIGHT = 0.6
CATEGORY_WEIGHT = 0.5

# How good each kind of word match is.
EXACT_SCORE = 1.0
PREFIX_SCORE = 0.9
SUBSTRING_SCORE = 0.7
FUZZY_SCORE = 0.5

# Typo tolerance: tokens shorter than this are never matched fuzzily,
# because short words are too similar to each other.
FUZZY_MIN_LENGTH = 4
FUZZY_MIN_RATIO = 0.8

EXACT_NAME_BONUS = 1.0
NAME_PREFIX_BONUS = 0.5

_WORD_RE = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase words; case and punctuation are ignored."""
    return _WORD_RE.findall(text.casefold())


def word_match_score(token: str, word: str) -> float:
    """How well a single query token matches a single word (0 = no match)."""
    if token == word:
        return EXACT_SCORE
    if word.startswith(token):
        return PREFIX_SCORE
    if token in word:
        return SUBSTRING_SCORE
    if len(token) >= FUZZY_MIN_LENGTH:
        # Compare with the whole word and with its beginning, so that a typo
        # in a partially typed word ("calcu" -> "clacu") still matches.
        ratio = max(
            SequenceMatcher(None, token, word).ratio(),
            SequenceMatcher(None, token, word[: len(token)]).ratio(),
        )
        if ratio >= FUZZY_MIN_RATIO:
            return FUZZY_SCORE * ratio
    return 0.0


def _best_field_score(token: str, words: list[str]) -> float:
    return max((word_match_score(token, word) for word in words), default=0.0)


def score_command(query: str, command: Command) -> float:
    """Relevance of a command for the query; 0 means "does not match"."""
    tokens = tokenize(query)
    if not tokens:
        return 0.0

    name_words = tokenize(command.name)
    description_words = tokenize(command.description)
    category_words = tokenize(command.type.label) + list(command.type.keywords)

    total = 0.0
    for token in tokens:
        token_score = max(
            NAME_WEIGHT * _best_field_score(token, name_words),
            DESCRIPTION_WEIGHT * _best_field_score(token, description_words),
            CATEGORY_WEIGHT * _best_field_score(token, category_words),
        )
        if token_score == 0.0:
            return 0.0
        total += token_score

    name = " ".join(name_words)
    phrase = " ".join(tokens)
    if name == phrase:
        total += EXACT_NAME_BONUS
    elif name.startswith(phrase):
        total += NAME_PREFIX_BONUS
    return total


def search(query: str, commands: Iterable[Command]) -> list[Command]:
    """Return matching commands, the most relevant first.

    An empty query returns all commands in their original order.
    Commands with equal scores are sorted by name.
    """
    commands = list(commands)
    if not tokenize(query):
        return commands

    scored = [(score_command(query, command), command) for command in commands]
    matches = [(score, command) for score, command in scored if score > 0]
    matches.sort(key=lambda item: (-item[0], item[1].name.casefold()))
    return [command for _, command in matches]
