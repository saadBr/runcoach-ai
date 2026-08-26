"""Tests for the core SQLAlchemy persistence schema."""

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from runcoach.db.base import Base
from runcoach.db.models import Activity, Athlete


def _unique_column_sets(table: Table) -> set[frozenset[str]]:
    """Return columns covered by table-level unique constraints."""

    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _index_column_sets(table: Table) -> set[frozenset[str]]:
    """Return columns covered by explicitly declared indexes."""

    return {frozenset(column.name for column in index.columns) for index in table.indexes}


def test_documented_core_tables_are_registered() -> None:
    expected_tables = {
        "athletes",
        "import_batches",
        "import_files",
        "activities",
        "source_activities",
        "activity_field_sources",
        "data_quality_issues",
        "source_activity_files",
        "laps",
        "trackpoints",
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


def test_activity_can_reference_its_canonical_sensor_source() -> None:
    source_foreign_key = next(iter(Activity.__table__.c.canonical_sensor_source_id.foreign_keys))

    assert source_foreign_key.target_fullname == "source_activities.id"
    assert Activity.__table__.c.canonical_sensor_source_id.nullable


def test_provider_external_activity_id_is_unique() -> None:
    source_activity_table = Base.metadata.tables["source_activities"]
    unique_columns = _unique_column_sets(source_activity_table)

    assert frozenset({"provider", "external_activity_id"}) in unique_columns


def test_import_file_hash_is_indexed_for_idempotency_lookup() -> None:
    import_file_table = Base.metadata.tables["import_files"]
    indexed_columns = _index_column_sets(import_file_table)

    assert frozenset({"sha256"}) in indexed_columns


def test_data_quality_issue_requires_an_identifiable_scope() -> None:
    issue_table = Base.metadata.tables["data_quality_issues"]
    constraint_names = {
        constraint.name
        for constraint in issue_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "data_quality_issues_scope" in constraint_names


def test_source_activity_file_link_is_unique() -> None:
    link_table = Base.metadata.tables["source_activity_files"]
    unique_columns = _unique_column_sets(link_table)

    assert frozenset({"source_activity_id", "import_file_id"}) in unique_columns


def test_lap_index_is_unique_per_activity() -> None:
    lap_table = Base.metadata.tables["laps"]
    unique_columns = _unique_column_sets(lap_table)

    assert frozenset({"activity_id", "lap_index"}) in unique_columns


def test_trackpoint_uses_activity_and_sequence_composite_key() -> None:
    trackpoint_table = Base.metadata.tables["trackpoints"]
    primary_key_columns = {column.name for column in trackpoint_table.primary_key.columns}

    assert primary_key_columns == {"activity_id", "sequence_number"}
