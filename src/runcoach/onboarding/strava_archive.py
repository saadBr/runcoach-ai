"""Bounded validation and selective extraction for private Strava ZIP exports."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 768 * 1024 * 1024
MAX_CSV_BYTES = 64 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
SUPPORTED_SENSOR_SUFFIXES = (".fit", ".fit.gz", ".gpx")
SUPPORTED_COMPRESSIONS = frozenset({ZIP_STORED, ZIP_DEFLATED})


class StravaArchiveError(ValueError):
    """Raised with a sanitized code when a ZIP cannot be accepted safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtractedArchiveMember:
    """One safely extracted member with a provider-relative logical name."""

    logical_name: str
    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExtractedStravaArchive:
    """Required summary and supported sensor files extracted from one archive."""

    activities_csv: ExtractedArchiveMember
    sensor_files: tuple[ExtractedArchiveMember, ...]
    archive_entries: int
    expanded_bytes: int


def _safe_parts(info: ZipInfo) -> tuple[str, ...]:
    name = info.filename
    if not name or len(name) > 1_024 or "\\" in name or "\x00" in name:
        raise StravaArchiveError("ARCHIVE_PATH_INVALID", "The archive contains an unsafe path.")
    path = PurePosixPath(name)
    parts = path.parts
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].endswith(":")
    ):
        raise StravaArchiveError("ARCHIVE_PATH_INVALID", "The archive contains an unsafe path.")
    return parts


def _validate_entries(entries: list[ZipInfo]) -> tuple[ZipInfo, tuple[str, ...]]:
    if not entries:
        raise StravaArchiveError("ARCHIVE_EMPTY", "The Strava archive is empty.")
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise StravaArchiveError(
            "ARCHIVE_TOO_MANY_ENTRIES",
            "The Strava archive contains too many entries.",
        )

    names: set[str] = set()
    csv_candidates: list[tuple[ZipInfo, tuple[str, ...]]] = []
    for info in entries:
        parts = _safe_parts(info)
        normalized_name = "/".join(parts).casefold()
        if normalized_name in names:
            raise StravaArchiveError(
                "ARCHIVE_DUPLICATE_PATH",
                "The archive contains duplicate paths.",
            )
        names.add(normalized_name)
        if not info.is_dir() and parts[-1].casefold() == "activities.csv":
            csv_candidates.append((info, parts))

    if len(csv_candidates) != 1:
        raise StravaArchiveError(
            "ACTIVITIES_CSV_REQUIRED",
            "The Strava archive must contain exactly one activities.csv file.",
        )
    csv_info, csv_parts = csv_candidates[0]
    if csv_info.file_size > MAX_CSV_BYTES:
        raise StravaArchiveError(
            "ACTIVITIES_CSV_TOO_LARGE",
            "The Strava activities.csv file is too large.",
        )
    prefix = csv_parts[:-1]
    expected_sensor_root = (*prefix, "activities")
    expanded_bytes = 0
    for info in entries:
        parts = _safe_parts(info)
        is_sensor = (
            not info.is_dir()
            and len(parts) > len(expected_sensor_root)
            and tuple(part.casefold() for part in parts[: len(expected_sensor_root)])
            == tuple(part.casefold() for part in expected_sensor_root)
            and _sensor_suffix("/".join(parts[len(prefix) :])) is not None
        )
        if info is not csv_info and not is_sensor:
            continue
        if info.flag_bits & 0x1:
            raise StravaArchiveError(
                "ARCHIVE_ENCRYPTED_ENTRY",
                "Encrypted Strava activity entries are not supported.",
            )
        if S_ISLNK(info.external_attr >> 16):
            raise StravaArchiveError(
                "ARCHIVE_LINK_ENTRY",
                "Link entries are not accepted as Strava activity evidence.",
            )
        if info.compress_type not in SUPPORTED_COMPRESSIONS:
            raise StravaArchiveError(
                "ARCHIVE_COMPRESSION_UNSUPPORTED",
                "The archive uses an unsupported compression method for activity evidence.",
            )
        if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise StravaArchiveError(
                "ARCHIVE_MEMBER_TOO_LARGE",
                "A Strava activity entry is too large.",
            )
        expanded_bytes += info.file_size
        if expanded_bytes > MAX_EXPANDED_BYTES:
            raise StravaArchiveError(
                "ARCHIVE_EXPANSION_TOO_LARGE",
                "The extracted Strava activity evidence is too large.",
            )
    return csv_info, prefix


def _sensor_suffix(logical_name: str) -> str | None:
    lowered = logical_name.casefold()
    for suffix in SUPPORTED_SENSOR_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    return None


def _extract_member(
    archive: ZipFile,
    info: ZipInfo,
    target: Path,
    *,
    maximum_bytes: int,
) -> int:
    written = 0
    try:
        with archive.open(info, "r") as source, target.open("wb") as destination:
            while chunk := source.read(COPY_CHUNK_BYTES):
                written += len(chunk)
                if written > maximum_bytes or written > info.file_size:
                    raise StravaArchiveError(
                        "ARCHIVE_MEMBER_TOO_LARGE",
                        "A Strava archive entry exceeded its accepted size.",
                    )
                destination.write(chunk)
    except (BadZipFile, RuntimeError) as error:
        raise StravaArchiveError(
            "ARCHIVE_CONTENT_INVALID",
            "The Strava archive contains invalid compressed content.",
        ) from error
    if written != info.file_size:
        raise StravaArchiveError(
            "ARCHIVE_SIZE_MISMATCH",
            "A Strava archive entry has inconsistent size metadata.",
        )
    return written


def extract_strava_archive(
    archive_path: Path,
    destination: Path,
) -> ExtractedStravaArchive:
    """Validate every ZIP entry and extract only supported private activity evidence."""

    if not archive_path.is_file() or archive_path.stat().st_size <= 0:
        raise StravaArchiveError("ARCHIVE_EMPTY", "Upload a non-empty Strava ZIP archive.")
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise StravaArchiveError("ARCHIVE_TOO_LARGE", "The Strava ZIP archive is too large.")
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(archive_path) as archive:
            entries = archive.infolist()
            csv_info, prefix = _validate_entries(entries)
            csv_path = destination / "activities.csv"
            csv_size = _extract_member(
                archive,
                csv_info,
                csv_path,
                maximum_bytes=MAX_CSV_BYTES,
            )
            sensors: list[ExtractedArchiveMember] = []
            expected_sensor_root = (*prefix, "activities")
            for info in entries:
                if info.is_dir():
                    continue
                parts = _safe_parts(info)
                if len(parts) <= len(expected_sensor_root):
                    continue
                if tuple(part.casefold() for part in parts[: len(expected_sensor_root)]) != tuple(
                    part.casefold() for part in expected_sensor_root
                ):
                    continue
                logical_parts = parts[len(prefix) :]
                logical_name = "/".join(logical_parts)
                suffix = _sensor_suffix(logical_name)
                if suffix is None:
                    continue
                sensor_path = destination / f"sensor-{len(sensors):05d}{suffix}"
                size_bytes = _extract_member(
                    archive,
                    info,
                    sensor_path,
                    maximum_bytes=MAX_MEMBER_BYTES,
                )
                sensors.append(
                    ExtractedArchiveMember(
                        logical_name=logical_name,
                        path=sensor_path,
                        size_bytes=size_bytes,
                    )
                )
    except BadZipFile as error:
        raise StravaArchiveError(
            "ARCHIVE_INVALID",
            "The uploaded file is not a valid ZIP archive.",
        ) from error

    return ExtractedStravaArchive(
        activities_csv=ExtractedArchiveMember(
            logical_name="activities.csv",
            path=csv_path,
            size_bytes=csv_size,
        ),
        sensor_files=tuple(sensors),
        archive_entries=len(entries),
        expanded_bytes=sum(info.file_size for info in entries),
    )
