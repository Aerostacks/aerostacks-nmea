"""Pure NMEA-0183 sentence parsing helpers.

The parsers mutate a shared :class:`EstimateData` dataclass that accumulates
the latest position, velocity, fix type and DOP values.

Only the sentences most commonly needed are implemented:

* ``GGA`` - fix quality, lat/lon/alt, satellite count, HDOP
* ``RMC`` - time, ground speed, course-over-ground
* ``GSA`` - fix type (1=no fix, 2=2D, 3=3D), HDOP, VDOP
* ``VTG`` - course-over-ground and speed in knots / km/h

Any talker prefix (``GP``, ``GN``, ``GL``, ``GA``, ``GB``/``BD``) is
accepted; the parser keys on the 3-letter sentence code.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

KNOTS_TO_MS = 0.514444

# Fix types stored in EstimateData.gps_fix_type (MAVLink GPS_FIX_TYPE values).
FIX_NO_GPS = 0
FIX_NO_FIX = 1
FIX_2D = 2
FIX_3D = 3
FIX_DGPS = 4
FIX_RTK_FLOAT = 5
FIX_RTK_FIXED = 6


@dataclass
class EstimateData:
    time: int | None = None
    last_update: str = "INIT"
    vx: float | None = None
    vy: float | None = None
    vz: float | None = None
    gps_fix_type: int | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt: float | None = None
    gps_hdop: float | None = None
    gps_vdop: float | None = None
    gps_satellites: int | None = None
    # Latest GSA mode (1 no fix, 2 2D, 3 3D). Not a position column; it only
    # lets GGA report a plain fix as 2D instead of 3D.
    gsa_fix_mode: int | None = None


def verify_checksum(sentence: str) -> bool:
    """Validate an NMEA sentence's XOR checksum.

    Accepts sentences with or without a leading ``$`` and with or without
    the trailing ``\\r\\n``. Returns ``False`` when no ``*`` checksum
    delimiter is present so callers can drop garbled lines.
    """
    s = sentence.strip()
    if s.startswith("$"):
        s = s[1:]
    if "*" not in s:
        return False
    body, _, cksum = s.rpartition("*")
    cksum = cksum.strip()[:2]
    if len(cksum) != 2:
        return False
    computed = 0
    for ch in body:
        computed ^= ord(ch)
    try:
        expected = int(cksum, 16)
    except ValueError:
        return False
    return computed == expected


def _parse_lat_lon(value: str, hemisphere: str) -> float | None:
    """Convert NMEA ``ddmm.mmmm`` / ``dddmm.mmmm`` to signed decimal degrees."""
    if not value or not hemisphere:
        return None
    try:
        # Latitude has 2 degree digits, longitude has 3. Detect by locating
        # the decimal point: minutes always occupy 2 digits before the dot.
        dot = value.find(".")
        deg_len = (dot if dot >= 0 else len(value)) - 2
        if deg_len <= 0:
            return None
        degrees = float(value[:deg_len])
        minutes = float(value[deg_len:])
    except ValueError:
        return None
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _safe_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_int(value: str) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _gga_quality_to_fix_type(quality: int | None) -> int | None:
    """Map GGA fix-quality to a MAVLink-style ``GPS_FIX_TYPE`` value.

    Fix types used by :class:`EstimateData`:
    0 NO_GPS, 1 NO_FIX, 2 2D, 3 3D, 4 DGPS, 5 RTK_FLOAT, 6 RTK_FIXED.
    GGA only tells us about correction quality so we fall back to 3 (3D)
    for a plain fix; the latest GSA mode refines that to 2D when applicable.
    """
    if quality is None:
        return None
    if quality == 0:
        return 1
    if quality == 1:
        return 3
    if quality == 2:
        return 4
    if quality == 4:
        return 6
    if quality == 5:
        return 5
    return 3


def split_sentence(line: str) -> tuple[str, list[str]] | None:
    """Strip ``$``/checksum and return ``(sentence_code, fields)``.

    Returns ``None`` for malformed lines or bad checksums. ``sentence_code``
    is the 3-character mnemonic (``GGA``, ``RMC``, ...), talker-stripped.
    """
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None
    if not verify_checksum(line):
        return None
    body = line[1 : line.rfind("*")]
    parts = body.split(",")
    if not parts or len(parts[0]) < 5:
        return None
    code = parts[0][2:5].upper()
    return code, parts[1:]


def gga_has_fix(sentence: str) -> bool:
    """Require a checksum-valid GGA with a fix and usable position coordinates."""
    sentence = sentence.strip()
    if not re.fullmatch(r"\$[A-Z]{2}GGA", sentence.partition(",")[0]):
        return False
    parsed = split_sentence(sentence)
    if parsed is None or parsed[0] != "GGA" or len(parsed[1]) < 6:
        return False
    fields = parsed[1]
    if fields[5] not in {"1", "2", "3", "4", "5", "6", "7", "8"}:
        return False
    if len(sentence.rpartition("*")[2]) != 2:
        return False
    for value, hemisphere, directions, width, maximum in (
        (fields[1], fields[2], ("N", "S"), 4, 90),
        (fields[3], fields[4], ("E", "W"), 5, 180),
    ):
        if hemisphere not in directions or not re.fullmatch(
            rf"[0-9]{{{width}}}(?:\.[0-9]+)?", value
        ):
            return False
        degrees = int(value[: width - 2])
        minutes = float(value[width - 2 :])
        if minutes >= 60 or degrees > maximum or (degrees == maximum and minutes != 0):
            return False
    return True


def _parse_gga(estimate: EstimateData, fields: list[str], pi_time: int) -> bool:
    if len(fields) < 9:
        return False
    lat = _parse_lat_lon(fields[1], fields[2])
    lon = _parse_lat_lon(fields[3], fields[4])
    quality = _safe_int(fields[5])
    sats = _safe_int(fields[6])
    hdop = _safe_float(fields[7])
    alt = _safe_float(fields[8])

    estimate.time = pi_time
    estimate.last_update = "NMEA_GGA"
    estimate.gps_lat = lat
    estimate.gps_lon = lon
    estimate.gps_alt = alt
    estimate.gps_hdop = hdop
    estimate.gps_satellites = sats
    # Every GGA carries the receiver's current fix quality, so it always
    # replaces the previous value: the fix type must be able to drop (RTK
    # fixed -> float -> plain -> none), not just ratchet upwards.
    fix_type = _gga_quality_to_fix_type(quality)
    if fix_type == 3 and estimate.gsa_fix_mode == 2:
        fix_type = 2
    estimate.gps_fix_type = fix_type
    return True


def _parse_rmc(estimate: EstimateData, fields: list[str], pi_time: int) -> bool:
    if len(fields) < 9:
        return False
    status = fields[1]
    if status != "A":
        # 'V' = void (no fix). Keep last known values but don't synthesize a
        # row from RMC alone — we rely on GGA to drive emission.
        return False
    lat = _parse_lat_lon(fields[2], fields[3])
    lon = _parse_lat_lon(fields[4], fields[5])
    speed_knots = _safe_float(fields[6])
    course_deg = _safe_float(fields[7])

    estimate.time = pi_time
    estimate.last_update = "NMEA_RMC"
    if lat is not None:
        estimate.gps_lat = lat
    if lon is not None:
        estimate.gps_lon = lon

    if speed_knots is not None and course_deg is not None:
        speed_ms = speed_knots * KNOTS_TO_MS
        course_rad = math.radians(course_deg)
        # NED: vx north, vy east, vz down (no vertical info from RMC).
        estimate.vx = speed_ms * math.cos(course_rad)
        estimate.vy = speed_ms * math.sin(course_rad)
        estimate.vz = 0.0
    return True


def _parse_gsa(estimate: EstimateData, fields: list[str], pi_time: int) -> bool:
    if len(fields) < 17:
        return False
    fix_mode = _safe_int(fields[1])
    # GSA mode: 1=no fix, 2=2D, 3=3D. GGA is authoritative for the fix type;
    # GSA only distinguishes 2D from 3D while GGA reports a plain fix.
    estimate.gsa_fix_mode = fix_mode
    if fix_mode in (2, 3) and estimate.gps_fix_type in (2, 3):
        estimate.gps_fix_type = fix_mode
    # Last 3 fields before the checksum slot are PDOP, HDOP, VDOP.
    pdop = _safe_float(fields[14])  # noqa: F841 — kept for future use
    hdop = _safe_float(fields[15])
    vdop = _safe_float(fields[16])
    if hdop is not None:
        estimate.gps_hdop = hdop
    if vdop is not None:
        estimate.gps_vdop = vdop
    estimate.time = pi_time
    estimate.last_update = "NMEA_GSA"
    return True


def _parse_vtg(estimate: EstimateData, fields: list[str], pi_time: int) -> bool:
    if len(fields) < 7:
        return False
    course_deg = _safe_float(fields[0])
    speed_knots = _safe_float(fields[4])
    if speed_knots is None or course_deg is None:
        return False
    speed_ms = speed_knots * KNOTS_TO_MS
    course_rad = math.radians(course_deg)
    estimate.vx = speed_ms * math.cos(course_rad)
    estimate.vy = speed_ms * math.sin(course_rad)
    estimate.vz = 0.0
    estimate.time = pi_time
    estimate.last_update = "NMEA_VTG"
    return True


_PARSERS = {
    "GGA": _parse_gga,
    "RMC": _parse_rmc,
    "GSA": _parse_gsa,
    "VTG": _parse_vtg,
}


def parse_sentence(
    estimate: EstimateData, line: str, pi_time: int
) -> tuple[str, bool] | None:
    """Parse a raw NMEA line into ``estimate``.

    Returns ``(sentence_code, should_emit)`` where ``should_emit`` is
    ``True`` only on GGA — the controller uses GGA as the heartbeat that
    triggers a row insert. Returns ``None`` for ignored or invalid lines.
    """
    parsed = split_sentence(line)
    if parsed is None:
        return None
    code, fields = parsed
    handler: Any = _PARSERS.get(code)
    if handler is None:
        return None
    if not handler(estimate, fields, pi_time):
        return None
    return code, code == "GGA"
