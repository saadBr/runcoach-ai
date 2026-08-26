"""Tests for the core SQLAlchemy persistence schema."""

from sqlalchemy import Table, UniqueConstraint

from runcoach.db.base import Base
from runcoach.db.models import Activity, Athlete


def _unique_column_sets(table: Table) -> set[frozenset[str]]:
    """Return the column sets covered by table-level unique constraints."""

    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_core_tables_are_registered() -> None:
    expected_tables = {
        "athletes",
        "import_batches",
        "source_files",
        "activities",
        "activity_sources",
        "activity_field_sources",
        "validation_findings",
    }

    assert expected_tables <= set(Base.metadata.tables)


def test_athlete_identity_and_timezone_are_required() -> None:
    assert Athlete.__table__.c.id.primary_key
    assert not Athlete.__table__.c.timezone.nullable
    assert Athlete.__table__.c.display_name.nullable


def test_activity_retains_athlete_ownership() -> None:
    athlete_foreign_key = next(iter(Activity.__table__.c.athlete_id.foreign_keys))

    assert athlete_foreign_key.target_fullname == "athletes.id"
    assert not Activity.__table__.c.athlete_id.nullable


def test_activity_canonical_key_is_unique_per_athlete() -> None:
    activity_table = Base.metadata.tables["activities"]
    unique_columns = _unique_column_sets(activity_table)

    assert frozenset({"athlete_id", "canonical_key"}) in unique_columns


def test_source_file_hash_is_unique_per_athlete_and_provider() -> None:
    source_file_table = Base.metadata.tables["source_files"]
    unique_columns = _unique_column_sets(source_file_table)

    assert frozenset({"athlete_id", "provider", "content_sha256"}) in unique_columns
