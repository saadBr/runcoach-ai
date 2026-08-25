"""Tests for secure GPX activity parsing."""

from pathlib import Path
from uuid import UUID

from runcoach.ingestion import parse_gpx_activity

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")

VALID_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx
    version="1.1"
    creator="RunCoach test"
    xmlns="http://www.topografix.com/GPX/1/1"
>
  <trk>
    <name>Synthetic historical run</name>
    <trkseg>
      <trkpt lat="33.500000" lon="-7.600000">
        <ele>10.5</ele>
        <time>2026-04-01T06:30:00Z</time>
      </trkpt>
      <trkpt lat="33.500100" lon="-7.600100">
        <ele>11.0</ele>
        <time>2026-04-01T06:31:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_valid_gpx_produces_timestamped_trackpoints(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.gpx"
    _write(path, VALID_GPX)

    result = parse_gpx_activity(path, ATHLETE_ID)

    assert result.findings == ()
    assert len(result.activities) == 1

    activity = result.activities[0]
    assert activity.elapsed_time_s == 60
    assert len(activity.trackpoints) == 2
    assert activity.trackpoints[0].sequence == 0
    assert activity.trackpoints[0].latitude_deg == 33.5
    assert activity.trackpoints[0].longitude_deg == -7.6
    assert activity.trackpoints[0].altitude_m == 10.5


def test_invalid_trackpoint_is_reported_and_skipped(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partial.gpx"
    _write(
        path,
        VALID_GPX.replace(
            "<time>2026-04-01T06:30:00Z</time>",
            "",
        ),
    )

    result = parse_gpx_activity(path, ATHLETE_ID)

    assert len(result.activities) == 1
    assert len(result.activities[0].trackpoints) == 1
    assert len(result.findings) == 1
    assert result.findings[0].code == "GPX_TRACKPOINT_INVALID"


def test_malformed_xml_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "malformed.gpx"
    _write(path, "<gpx><trk>")

    result = parse_gpx_activity(path, ATHLETE_ID)

    assert result.activities == ()
    assert result.findings[0].code == "GPX_XML_INVALID"


def test_xml_entity_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "entity.gpx"
    _write(
        path,
        """\
<?xml version="1.0"?>
<!DOCTYPE gpx [
  <!ENTITY private SYSTEM "file:///private-data">
]>
<gpx><trk><name>&private;</name></trk></gpx>
""",
    )

    result = parse_gpx_activity(path, ATHLETE_ID)

    assert result.activities == ()
    assert result.findings[0].code == "GPX_XML_INVALID"


def test_file_without_valid_trackpoints_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empty.gpx"
    _write(
        path,
        """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg /></trk>
</gpx>
""",
    )

    result = parse_gpx_activity(path, ATHLETE_ID)

    assert result.activities == ()
    assert result.findings[-1].code == "GPX_NO_VALID_TRACKPOINTS"
