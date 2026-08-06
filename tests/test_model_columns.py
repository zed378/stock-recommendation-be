"""Every declared field must actually be a column.

`enum_column` returns a *type*, so it has to be wrapped:

    method: Mapped[TagMethod] = mapped_column(enum_column(TagMethod))

Written without the wrapper it looks entirely reasonable, and SQLAlchemy
accepts it in silence - the annotation is there, the attribute is there, and
the column simply is not. Nothing fails at import, nothing fails at mapping,
and the first sign is an insert against a table missing a NOT NULL column, or
a migration that appears to add a column the models supposedly do not have.

That happened here, and it was found by diffing the schema against a real
PostgreSQL database rather than by any test. This is that check, reduced to
something the ordinary suite can run.
"""

from __future__ import annotations

import annotationlib
import pytest
from sqlalchemy.orm import DeclarativeBase

import aidss.db.models  # noqa: F401  - registers every mapper
from aidss.db.base import Base


def mapped_classes() -> list[type[DeclarativeBase]]:
    return [mapper.class_ for mapper in Base.registry.mappers]


@pytest.mark.parametrize("model", mapped_classes(), ids=lambda m: m.__name__)
def test_every_mapped_annotation_became_a_column(model) -> None:
    """A `Mapped[...]` annotation with no column behind it is a silent hole."""
    columns = set(model.__table__.columns.keys())
    relationships = set(model.__mapper__.relationships.keys())

    # Read as strings rather than resolved. Several model modules import their
    # related classes only under TYPE_CHECKING, so resolving raises NameError
    # on a perfectly correct model - the test would then be reporting on its own
    # import graph instead of on the schema.
    annotations: dict[str, str] = {}
    for klass in reversed(model.__mro__):
        annotations.update(
            annotationlib.get_annotations(klass, format=annotationlib.Format.STRING)
        )

    missing = []
    for name, annotation in annotations.items():
        if name.startswith("_") or name in relationships:
            continue
        if not annotation.startswith("Mapped["):
            continue
        # `mapped_column(name=...)` can rename, so fall back to the attribute
        # the mapper actually exposes rather than assuming the two agree.
        attribute = model.__mapper__.attrs.get(name)
        key = getattr(getattr(attribute, "columns", [None])[0], "key", None)
        if name not in columns and key not in columns:
            missing.append(name)

    assert not missing, (
        f"{model.__name__} declares {missing} as Mapped[...] but has no column for "
        "them. A likely cause is assigning a *type* directly - "
        "`x: Mapped[E] = enum_column(E)` instead of "
        "`mapped_column(enum_column(E))`."
    )
