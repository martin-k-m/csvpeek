"""Fixtures shared by the test modules."""

import csv

import pytest


@pytest.fixture
def squeezed_field_limit():
    """Lower the csv field size limit for one test, and yield the new value.

    Lets the oversized-field tests provoke the error with a fifty character
    field instead of a ten megabyte one.
    """
    small = 50
    previous = csv.field_size_limit(small)
    try:
        yield small
    finally:
        csv.field_size_limit(previous)
