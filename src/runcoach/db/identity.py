"""Identity primitives and safe bootstrap for the existing local athlete."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import scrypt
from hmac import compare_digest
from secrets import token_bytes
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.db.models import (
    Athlete,
    AthleteOnboarding,
    Goal,
    ImportBatch,
    ImportFile,
    TrainingPlan,
    UserAccount,
)

PASSWORD_HASH_SCHEME = "scrypt"
PASSWORD_HASH_VERSION = 1
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
PASSWORD_MAX_MEMORY_BYTES = 64 * 1024 * 1024
MINIMUM_PASSWORD_LENGTH = 12
MAXIMUM_PASSWORD_LENGTH = 1024


class IdentityError(RuntimeError):
    """Raised when an identity operation cannot be completed safely."""


class IdentityConflictError(IdentityError):
    """Raised when requested identity data conflicts with persisted ownership."""


@dataclass(frozen=True, slots=True)
class BootstrappedAccount:
    """Privacy-minimized result of claiming an existing local athlete."""

    account_id: UUID
    created: bool
    account_status: str
    onboarding_status: str


def normalize_email(email: str) -> str:
    """Return the stable login representation for an email address."""

    normalized = email.strip().casefold()
    local_part, separator, domain = normalized.partition("@")
    if (
        not separator
        or not local_part
        or not domain
        or "." not in domain
        or any(character.isspace() for character in normalized)
        or len(normalized) > 320
    ):
        raise ValueError("Enter a valid email address.")
    return normalized


def validate_password(password: str) -> None:
    """Validate the minimum password policy without storing or logging the value."""

    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters.")
    if len(password) > MAXIMUM_PASSWORD_LENGTH:
        raise ValueError("Password is too long.")


def _derive_password_hash(
    password: str,
    *,
    salt: bytes,
    n: int,
    r: int,
    p: int,
) -> bytes:
    return scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=PASSWORD_MAX_MEMORY_BYTES,
        dklen=PASSWORD_HASH_BYTES,
    )


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Create a salted, versioned scrypt password hash."""

    validate_password(password)
    effective_salt = salt or token_bytes(PASSWORD_SALT_BYTES)
    if len(effective_salt) != PASSWORD_SALT_BYTES:
        raise ValueError("Password salt has an invalid length.")
    derived = _derive_password_hash(
        password,
        salt=effective_salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
    )
    return "$".join(
        (
            PASSWORD_HASH_SCHEME,
            str(PASSWORD_HASH_VERSION),
            str(PASSWORD_SCRYPT_N),
            str(PASSWORD_SCRYPT_R),
            str(PASSWORD_SCRYPT_P),
            effective_salt.hex(),
            derived.hex(),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password without exposing parsing or comparison timing details."""

    try:
        scheme, version_text, n_text, r_text, p_text, salt_hex, expected_hex = encoded_hash.split(
            "$"
        )
        if scheme != PASSWORD_HASH_SCHEME or int(version_text) != PASSWORD_HASH_VERSION:
            return False
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        if (n, r, p) != (PASSWORD_SCRYPT_N, PASSWORD_SCRYPT_R, PASSWORD_SCRYPT_P):
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        if len(salt) != PASSWORD_SALT_BYTES or len(expected) != PASSWORD_HASH_BYTES:
            return False
        actual = _derive_password_hash(
            password,
            salt=salt,
            n=n,
            r=r,
            p=p,
        )
    except (TypeError, ValueError):
        return False
    return compare_digest(actual, expected)


class ExistingAthleteAccountService:
    """Attach credentials to a fully initialized local athlete without replacing it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def bootstrap(
        self,
        *,
        athlete_id: UUID,
        email: str,
        password: str,
    ) -> BootstrappedAccount:
        """Create or safely reuse the account for one existing athlete."""

        normalized_email = normalize_email(email)
        validate_password(password)
        try:
            with self._session.begin():
                return self._bootstrap(
                    athlete_id=athlete_id,
                    email_normalized=normalized_email,
                    password=password,
                )
        except IdentityError:
            raise
        except Exception as error:
            raise IdentityError("Account bootstrap failed and was rolled back.") from error

    def _bootstrap(
        self,
        *,
        athlete_id: UUID,
        email_normalized: str,
        password: str,
    ) -> BootstrappedAccount:
        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise IdentityError("The configured athlete profile does not exist.")

        existing_account = self._session.scalar(
            select(UserAccount).where(UserAccount.athlete_id == athlete_id)
        )
        if existing_account is not None:
            return self._reuse_existing_account(
                account=existing_account,
                email_normalized=email_normalized,
                password=password,
            )

        email_owner = self._session.scalar(
            select(UserAccount).where(UserAccount.email_normalized == email_normalized)
        )
        if email_owner is not None:
            raise IdentityConflictError("An account already uses that email address.")

        goal = self._active_primary_goal(athlete_id)
        plan = self._active_plan(goal.id)
        import_batch = self._latest_accepted_strava_batch(athlete_id)
        completed_at = datetime.now(UTC)

        account = UserAccount(
            athlete_id=athlete_id,
            email_normalized=email_normalized,
            password_hash=hash_password(password),
            status="active",
        )
        self._session.add(account)

        onboarding = self._session.get(AthleteOnboarding, athlete_id)
        if onboarding is None:
            onboarding = AthleteOnboarding(athlete_id=athlete_id)
            self._session.add(onboarding)
        onboarding.status = "ready"
        onboarding.strava_import_batch_id = import_batch.id
        onboarding.goal_id = goal.id
        onboarding.training_plan_id = plan.id
        onboarding.failure_code = None
        onboarding.completed_at = completed_at

        self._session.flush()
        return BootstrappedAccount(
            account_id=account.id,
            created=True,
            account_status=account.status,
            onboarding_status=onboarding.status,
        )

    def _reuse_existing_account(
        self,
        *,
        account: UserAccount,
        email_normalized: str,
        password: str,
    ) -> BootstrappedAccount:
        onboarding = self._session.get(AthleteOnboarding, account.athlete_id)
        if account.email_normalized != email_normalized or not verify_password(
            password, account.password_hash
        ):
            raise IdentityConflictError("The existing athlete account uses different credentials.")
        if account.status != "active" or onboarding is None or onboarding.status != "ready":
            raise IdentityConflictError("The existing athlete account is not ready for reuse.")
        return BootstrappedAccount(
            account_id=account.id,
            created=False,
            account_status=account.status,
            onboarding_status=onboarding.status,
        )

    def _active_primary_goal(self, athlete_id: UUID) -> Goal:
        goals = list(
            self._session.scalars(
                select(Goal).where(
                    Goal.athlete_id == athlete_id,
                    Goal.status == "active",
                    Goal.priority == "primary",
                )
            )
        )
        if len(goals) != 1:
            raise IdentityError("The existing athlete requires exactly one active primary goal.")
        return goals[0]

    def _active_plan(self, goal_id: UUID) -> TrainingPlan:
        plans = list(
            self._session.scalars(
                select(TrainingPlan).where(
                    TrainingPlan.goal_id == goal_id,
                    TrainingPlan.status == "active",
                )
            )
        )
        if len(plans) != 1:
            raise IdentityError("The existing athlete requires exactly one active training plan.")
        return plans[0]

    def _latest_accepted_strava_batch(self, athlete_id: UUID) -> ImportBatch:
        accepted_batch_ids = select(ImportFile.import_batch_id).where(
            ImportFile.source_provider == "strava",
            ImportFile.status == "accepted",
        )
        import_batch = self._session.scalar(
            select(ImportBatch)
            .where(
                ImportBatch.id.in_(accepted_batch_ids),
                ImportBatch.athlete_id == athlete_id,
                ImportBatch.status.in_(("completed", "completed_with_warnings")),
            )
            .order_by(ImportBatch.requested_at.desc())
            .limit(1)
        )
        if import_batch is None:
            raise IdentityError("The existing athlete has no accepted Strava import.")
        return import_batch
