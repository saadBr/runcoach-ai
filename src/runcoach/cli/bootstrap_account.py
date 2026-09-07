"""Attach a login account to the configured existing athlete profile."""

import argparse
import json
from dataclasses import asdict
from getpass import getpass
from uuid import UUID

from runcoach.config import get_settings
from runcoach.db.identity import (
    ExistingAthleteAccountService,
    IdentityError,
    normalize_email,
    validate_password,
)
from runcoach.db.session import SessionFactory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Attach login credentials to the configured existing athlete without replacing "
            "their profile, history, goal, or training plan."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Existing athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Collect private credentials interactively and bootstrap the account."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    athlete_id = parsed.athlete_id or get_settings().athlete_id
    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    email = input("Email: ").strip()
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")
    try:
        email = normalize_email(email)
        validate_password(password)
    except ValueError as error:
        parser.error(str(error))

    try:
        with SessionFactory() as session:
            result = ExistingAthleteAccountService(session).bootstrap(
                athlete_id=athlete_id,
                email=email,
                password=password,
            )
    except IdentityError as error:
        parser.error(str(error))

    print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
