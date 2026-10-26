"""Tests for the Ask-flow question router (deterministic heuristic path, no SLM).

Run:  python -m pytest -q tests/test_router.py
"""
import pytest

from nlq import _heuristic_route

DATA_QUESTIONS = [
    "Top 5 categories by spend this year",
    "How much did we spend on IT hardware?",
    "Which suppliers did we overpay?",
    "total maverick spend by category",
    "show me the highest spending suppliers",
]

DESCRIPTIVE_QUESTIONS = [
    "What is maverick spend?",
    "Explain tail spend",
    "How can I reduce off-contract spending?",
    "define supplier consolidation",
    "What does this tool do?",
]


@pytest.mark.parametrize("q", DATA_QUESTIONS)
def test_data_questions_route_to_sql(q):
    assert _heuristic_route(q) == "sql"


@pytest.mark.parametrize("q", DESCRIPTIVE_QUESTIONS)
def test_descriptive_questions_route_to_descriptive(q):
    assert _heuristic_route(q) == "descriptive"
