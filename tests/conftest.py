"""Fixtures shared by the test modules."""

import csv

import pytest


@pytest.fixture
def squeezed_field_limit():
    """Lower the csv field size limit for one test, and yield the new value.

    The oversized-field tests build a field one character past the limit. Read
    against the real limit that is a ten megabyte string written to disk three
    times over, which is a slow way to prove a fast thing. Squeezing the limit
    proves exactly the same behaviour with a fifty character field, and restores
    the real limit afterwards so no other test inherits the squeeze.
    """
    small = 50
    previous = csv.field_size_limit(small)
    try:
        yield small
    finally:
        csv.field_size_limit(previous)
