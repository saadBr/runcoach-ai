"""Tests for the existing-athlete account bootstrap CLI."""

import json
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.cli import bootstrap_account

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
ACCOUNT_ID = UUID("018f0000-0000-7000-8000-000000000002")


@dataclass(frozen=True)
class FakeBootstrapResult:
    """Serializable result returned by the fake identity service."""

    account_id: UUID
    created: bool
    account_status: str
    onboarding_status: str


def test_main_bootstraps_configured_athlete_without_printing_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    captured: list[tuple[UUID, str, str]] = []
    password_prompts: list[str] = []

    class FakeAccountService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def bootstrap(
            self,
            *,
            athlete_id: UUID,
            email: str,
            password: str,
        ) -> FakeBootstrapResult:
            captured.append((athlete_id, email, password))
            return FakeBootstrapResult(
                account_id=ACCOUNT_ID,
                created=True,
                account_status="active",
                onboarding_status="ready",
            )

    monkeypatch.setattr(
        bootstrap_account,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "athlete@example.com")

    def fake_getpass(prompt: str) -> str:
        password_prompts.append(prompt)
        return "correct horse battery staple"

    monkeypatch.setattr(bootstrap_account, "getpass", fake_getpass)
    monkeypatch.setattr(
        bootstrap_account,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        bootstrap_account,
        "ExistingAthleteAccountService",
        FakeAccountService,
    )

    assert bootstrap_account.main([]) == 0
    assert captured == [(ATHLETE_ID, "athlete@example.com", "correct horse battery staple")]
    assert password_prompts == ["Password: ", "Confirm password: "]

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output == {
        "account_id": str(ACCOUNT_ID),
        "account_status": "active",
        "created": True,
        "onboarding_status": "ready",
    }
    assert "athlete@example.com" not in output_text
    assert "correct horse" not in output_text


def test_main_rejects_password_confirmation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(("first secure password", "second secure password"))
    monkeypatch.setattr(
        bootstrap_account,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "athlete@example.com")
    monkeypatch.setattr(bootstrap_account, "getpass", lambda _prompt: next(responses))

    with pytest.raises(SystemExit) as error:
        bootstrap_account.main([])

    assert error.value.code == 2


def test_main_rejects_short_password_without_opening_a_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        bootstrap_account,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "athlete@example.com")
    monkeypatch.setattr(bootstrap_account, "getpass", lambda _prompt: "too short")
    monkeypatch.setattr(
        bootstrap_account,
        "SessionFactory",
        lambda: pytest.fail("A session must not open for an invalid password."),
    )

    with pytest.raises(SystemExit) as error:
        bootstrap_account.main([])

    assert error.value.code == 2
    assert "at least 12 characters" in capsys.readouterr().err


def test_main_requires_configured_athlete_before_collecting_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap_account,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        bootstrap_account.main([])

    assert error.value.code == 2
