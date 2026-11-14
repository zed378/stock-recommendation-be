"""Declarative base for schema `trading` (ADR-021).

Money, prices, and quantities are `NUMERIC(38,18)` and `Decimal` in code, never
a float type (ADR-025). The exchange returns them as strings and rejects a
quantity with too much precision, so binary floating point has no place here.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "trading"

#: One definition, so a test can assert no column uses anything else for money.
Money = Numeric(38, 18)


class Base(DeclarativeBase):
    metadata = MetaData(
        schema=SCHEMA,
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )
