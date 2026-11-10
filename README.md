# aerostacks-nmea

Small, dependency-free NMEA-0183 parser for GPS receivers.

Supports `GGA`, `RMC`, `GSA` and `VTG` from any talker (`GP`, `GN`, `GL`, `GA`,
`GB`/`BD`). Sentences are checksum-verified, and parsed values accumulate into a
single `EstimateData` object, so the latest position, velocity, fix type and DOP
are always available. The reported fix type follows the receiver: it can go down
as well as up (RTK fixed -> float -> DGPS -> 3D -> no fix).

## Install

```bash
uv add aerostacks-nmea
```

## Usage

```python
from aerostacks_nmea import EstimateData, parse_sentence

estimate = EstimateData()
lines = [
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
]
for line in lines:
    result = parse_sentence(estimate, line, 0)
    if result is not None:
        code, should_emit = result  # should_emit is True on GGA

print(estimate.gps_lat, estimate.gps_lon, estimate.gps_fix_type)
```

Other helpers: `verify_checksum`, `split_sentence`, `gga_has_fix` and the
`FIX_*` constants (MAVLink `GPS_FIX_TYPE` values).

## License

MIT
