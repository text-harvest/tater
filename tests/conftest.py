"""Shared fixtures for tater tests."""
import argparse
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

import pytest

from tater import SpanAnnotation


def pytest_addoption(parser):
    # Playwright runs headless unless given --headed; --headless is accepted so the
    # documented commands keep working. Dash's own pytest plugin also registers it when
    # dash[testing] is installed.
    try:
        parser.addoption("--headless", action="store_true", help="Accepted and ignored: Playwright is headless unless --headed.")
    except (ValueError, argparse.ArgumentError):
        pass


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

class Pet(BaseModel):
    kind: Optional[Literal["cat", "dog", "fish"]] = None
    neutered: Optional[bool] = None
    indoor: Optional[bool] = None
    breed: Optional[str] = None


class Address(BaseModel):
    city: Optional[str] = None
    zip: Optional[str] = None


class Owner(BaseModel):
    name: Optional[str] = None
    address: Optional[Address] = None


class Finding(BaseModel):
    label: Optional[Literal["positive", "negative", "uncertain"]] = None
    evidence: List[SpanAnnotation] = Field(default_factory=list)


class Measurements(BaseModel):
    weight: Optional[float] = None
    range_float: Optional[list[float]] = None
    range_int: Optional[list[int]] = None
    range_str: Optional[list[str]] = None


class Schema(BaseModel):
    pets: List[Pet] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    owner: Optional[Owner] = None
    overall: Optional[str] = None
    score: Optional[int] = None
    flags: List[Literal["urgent", "review"]] = Field(default_factory=list)
    measurements: Optional[Measurements] = None
    hl_path: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_schema():
    return Schema()


@pytest.fixture
def schema_with_pets():
    s = Schema()
    s.pets = [Pet(kind="cat", neutered=True), Pet(kind="dog")]
    return s


@pytest.fixture
def schema_with_findings():
    s = Schema()
    s.findings = [
        Finding(label="positive", evidence=[
            SpanAnnotation(start=0, end=5, text="hello", tag="Support"),
        ]),
        Finding(label="negative"),
    ]
    return s
