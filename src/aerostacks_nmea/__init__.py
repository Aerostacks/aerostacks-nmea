"""Dependency-free NMEA-0183 parsing for GPS receivers."""

from aerostacks_nmea._parser import (
    FIX_2D,
    FIX_3D,
    FIX_DGPS,
    FIX_NO_FIX,
    FIX_NO_GPS,
    FIX_RTK_FIXED,
    FIX_RTK_FLOAT,
    KNOTS_TO_MS,
    EstimateData,
    gga_has_fix,
    parse_sentence,
    split_sentence,
    verify_checksum,
)

__version__ = "0.1.0"

__all__ = [
    "FIX_2D",
    "FIX_3D",
    "FIX_DGPS",
    "FIX_NO_FIX",
    "FIX_NO_GPS",
    "FIX_RTK_FIXED",
    "FIX_RTK_FLOAT",
    "KNOTS_TO_MS",
    "EstimateData",
    "gga_has_fix",
    "parse_sentence",
    "split_sentence",
    "verify_checksum",
]
