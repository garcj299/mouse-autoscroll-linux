"""Scroll speed from the distance (in screen pixels) between the virtual
pointer and the autoscroll origin.

Two zones per axis:
* main zone: gentle growth from ``min_speed`` just outside the dead zone;
* edge zone: the last ``edge_zone`` fraction of the screen towards the edge
  you're moving to. Speed grows exponentially there, reaching ``max_speed``
  at the edge: "take me to the end of the page".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Curve:
    deadzone: float  # px around the origin with no scrolling
    min_speed: float  # notches/s right outside the dead zone
    slope: float  # main zone: min_speed + slope * (d - deadzone) ** exponent
    exponent: float
    edge_zone: float  # fraction of the screen size, e.g. 0.05
    max_speed: float  # notches/s, reached at the screen edge
    sensitivity: float = 1.0  # multiplies the main zone; the edge still ends at max_speed


def _main(distance: float, c: Curve) -> float:
    excess = max(distance - c.deadzone, 0.0)
    v = c.sensitivity * (c.min_speed + c.slope * excess**c.exponent)
    return min(v, c.max_speed)


def speed(
    offset: float,
    curve: Curve,
    edge_distance: float | None = None,
    screen_size: float | None = None,
) -> float:
    """Signed speed in wheel notches per second for one axis.

    ``edge_distance``: px from the origin to the screen edge in the direction
    of ``offset``; ``screen_size``: the screen's size along this axis. Without
    them (geometry unknown) only the main zone applies.
    """
    d = abs(offset)
    if d <= curve.deadzone:
        return 0.0
    v = _main(d, curve)
    if edge_distance is not None and screen_size:
        zone_start = max(edge_distance - curve.edge_zone * screen_size, curve.deadzone)
        if d >= zone_start:
            start_speed = _main(zone_start, curve)
            span = edge_distance - zone_start
            frac = 1.0 if span <= 0 else min((d - zone_start) / span, 1.0)
            if start_speed < curve.max_speed:
                v = start_speed * (curve.max_speed / start_speed) ** frac
    v = min(v, curve.max_speed)
    return v if offset > 0 else -v
