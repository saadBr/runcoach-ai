"""Tests for bounded, selective Strava ZIP extraction."""

from pathlib import Path
from stat import S_IFLNK
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from runcoach.onboarding import strava_archive
from runcoach.onboarding.strava_archive import StravaArchiveError, extract_strava_archive


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_extracts_only_summary_and_supported_activity_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "strava.zip"
    _write_zip(
        archive_path,
        {
            "export/activities.csv": b"Activity ID,Activity Date\n1,2026-09-01\n",
            "export/activities/1.fit": b"fit bytes",
            "export/activities/2.fit.gz": b"compressed fit bytes",
            "export/activities/3.gpx": b"gpx bytes",
            "export/photos/private.jpg": b"not extracted",
        },
    )

    extracted = extract_strava_archive(archive_path, tmp_path / "output")

    assert extracted.activities_csv.path.read_bytes().startswith(b"Activity ID")
    assert [member.logical_name for member in extracted.sensor_files] == [
        "activities/1.fit",
        "activities/2.fit.gz",
        "activities/3.gpx",
    ]
    assert [member.path.name for member in extracted.sensor_files] == [
        "sensor-00000.fit",
        "sensor-00001.fit.gz",
        "sensor-00002.gpx",
    ]
    assert not (tmp_path / "output" / "photos").exists()


@pytest.mark.parametrize(
    ("members", "expected_code"),
    (
        ({"../activities.csv": b"data"}, "ARCHIVE_PATH_INVALID"),
        ({"activities.csv": b"a", "ACTIVITIES.CSV": b"b"}, "ARCHIVE_DUPLICATE_PATH"),
        ({"readme.txt": b"no summary"}, "ACTIVITIES_CSV_REQUIRED"),
    ),
)
def test_rejects_unsafe_or_incomplete_archives(
    tmp_path: Path,
    members: dict[str, bytes],
    expected_code: str,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    _write_zip(archive_path, members)

    with pytest.raises(StravaArchiveError) as raised:
        extract_strava_archive(archive_path, tmp_path / "output")

    assert raised.value.code == expected_code


def test_rejects_link_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "link.zip"
    link = ZipInfo("activities/private.fit")
    link.create_system = 3
    link.external_attr = (S_IFLNK | 0o777) << 16
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("activities.csv", b"summary")
        archive.writestr(link, b"../../private")

    with pytest.raises(StravaArchiveError) as raised:
        extract_strava_archive(archive_path, tmp_path / "output")

    assert raised.value.code == "ARCHIVE_LINK_ENTRY"


def test_rejects_archive_larger_than_configured_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "large.zip"
    _write_zip(archive_path, {"activities.csv": b"summary"})
    monkeypatch.setattr(strava_archive, "MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(StravaArchiveError) as raised:
        extract_strava_archive(archive_path, tmp_path / "output")

    assert raised.value.code == "ARCHIVE_TOO_LARGE"


def test_ignored_media_does_not_consume_extraction_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "media-heavy.zip"
    _write_zip(
        archive_path,
        {
            "activities.csv": b"summary",
            "activities/1.fit": b"fit",
            "media/private-video.mp4": b"ignored media" * 100,
        },
    )
    monkeypatch.setattr(strava_archive, "MAX_EXPANDED_BYTES", 10)

    extracted = extract_strava_archive(archive_path, tmp_path / "output")

    assert [member.logical_name for member in extracted.sensor_files] == ["activities/1.fit"]


def test_rejects_activity_evidence_over_expansion_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "activity-heavy.zip"
    _write_zip(
        archive_path,
        {
            "activities.csv": b"summary",
            "activities/1.fit": b"four",
        },
    )
    monkeypatch.setattr(strava_archive, "MAX_EXPANDED_BYTES", 10)

    with pytest.raises(StravaArchiveError) as raised:
        extract_strava_archive(archive_path, tmp_path / "output")

    assert raised.value.code == "ARCHIVE_EXPANSION_TOO_LARGE"


def test_rejects_non_zip_content(tmp_path: Path) -> None:
    archive_path = tmp_path / "invalid.zip"
    archive_path.write_bytes(b"not a zip")

    with pytest.raises(StravaArchiveError) as raised:
        extract_strava_archive(archive_path, tmp_path / "output")

    assert raised.value.code == "ARCHIVE_INVALID"
