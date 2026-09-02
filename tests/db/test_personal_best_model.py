"""Schema tests for verified personal-best persistence."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from runcoach.db.base import Base
from runcoach.db.models import PersonalBest


def test_personal_best_table_is_registered() -> None:
    assert "personal_bests" in Base.metadata.tables
    assert PersonalBest.__table__.c.id.primary_key


def test_personal_best_links_athlete_and_activity() -> None:
    athlete_fk = next(iter(PersonalBest.__table__.c.athlete_id.foreign_keys))
    activity_fk = next(iter(PersonalBest.__table__.c.activity_id.foreign_keys))

    assert athlete_fk.target_fullname == "athletes.id"
    assert activity_fk.target_fullname == "activities.id"


def test_personal_best_has_evidence_uniqueness_and_domain_checks() -> None:
    personal_best_table = Base.metadata.tables["personal_bests"]
    unique_names = {
        constraint.name
        for constraint in personal_best_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_names = {
        constraint.name
        for constraint in personal_best_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "uq_personal_bests_evidence" in unique_names
    assert {
        "personal_bests_standard_distance",
        "personal_bests_elapsed_time",
        "personal_bests_effort_type",
        "personal_bests_verification_status",
        "personal_bests_superseded_after_achievement",
    } <= check_names
