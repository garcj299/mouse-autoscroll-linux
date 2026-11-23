import unittest

from mouse_autoscroll.curve import Curve
from mouse_autoscroll.engine import (
    BTN_LEFT,
    Geometry,
    BTN_MIDDLE,
    BTN_RIGHT,
    BTN_TASK,
    EV_KEY,
    EV_MSC,
    EV_REL,
    EV_SYN,
    IDLE,
    LATCHED,
    MSC_SCAN,
    REL_HWHEEL,
    REL_HWHEEL_HI_RES,
    REL_WHEEL,
    REL_WHEEL_HI_RES,
    REL_X,
    REL_Y,
    SCROLLING,
    SYN_REPORT,
    Engine,
    StateChange,
)
from mouse_autoscroll.modes import FULL, HOLD, IGNORE

CURVE = Curve(
    deadzone=12, min_speed=1.0, slope=0.0086, exponent=1.3, edge_zone=0.05, max_speed=250
)
SYN = (EV_SYN, SYN_REPORT, 0)


def press(code):
    return (EV_KEY, code, 1)


def release(code):
    return (EV_KEY, code, 0)


def move(dx=0, dy=0):
    out = []
    if dx:
        out.append((EV_REL, REL_X, dx))
    if dy:
        out.append((EV_REL, REL_Y, dy))
    return out


class Harness:
    """Feeds events to an engine and splits what comes out."""

    def __init__(self, mode=FULL, gain=1.0, geometry=None, free_pointer=True):
        self.mode = mode
        self.geometry = geometry
        self.lookups = 0
        self.geometry_lookups = 0
        self.engine = Engine(CURVE, self._mode_for_press, gain=gain,
                             geometry_for_press=self._geometry_for_press,
                             free_pointer=free_pointer)
        self.now = 0.0

    def _mode_for_press(self):
        self.lookups += 1
        return self.mode

    def _geometry_for_press(self):
        self.geometry_lookups += 1
        return self.geometry

    def feed(self, *events):
        out = []
        for ev in events:
            if isinstance(ev, list):
                for e in ev:
                    out += self.engine.handle(*e, now=self.now)
            else:
                out += self.engine.handle(*ev, now=self.now)
        return out

    def tick(self, dt, pointer=None):
        self.now += dt
        return self.engine.tick(self.now, pointer)

    def run_for(self, seconds, hz=120, pointer=None):
        out = []
        for _ in range(round(seconds * hz)):
            out += self.tick(1 / hz, pointer)
        return out


def events(out):
    return [o for o in out if isinstance(o, tuple)]


def states(out):
    return [o.state for o in out if isinstance(o, StateChange)]


def total(out, code):
    return sum(v for (t, c, v) in events(out) if t == EV_REL and c == code)


class PassthroughTest(unittest.TestCase):
    def test_motion_forwarded_when_idle(self):
        h = Harness()
        self.assertEqual(events(h.feed(move(dx=3))), [(EV_REL, REL_X, 3)])

    def test_left_click_forwarded_when_idle(self):
        h = Harness()
        out = h.feed(press(BTN_LEFT), release(BTN_LEFT))
        self.assertEqual(events(out), [press(BTN_LEFT), release(BTN_LEFT)])

    def test_syn_and_msc_always_forwarded(self):
        h = Harness()
        h.feed(press(BTN_MIDDLE))
        out = h.feed((EV_MSC, MSC_SCAN, 589827), SYN)
        self.assertEqual(events(out), [(EV_MSC, MSC_SCAN, 589827), SYN])

    def test_ignore_mode_forwards_middle_click(self):
        h = Harness(IGNORE)
        out = h.feed(press(BTN_MIDDLE), move(dy=200), release(BTN_MIDDLE))
        self.assertEqual(
            events(out), [press(BTN_MIDDLE), (EV_REL, REL_Y, 200), release(BTN_MIDDLE)]
        )
        self.assertEqual(states(out), [])


class FullModeTest(unittest.TestCase):
    def test_press_starts_scrolling_and_is_not_forwarded(self):
        h = Harness(FULL)
        out = h.feed(press(BTN_MIDDLE))
        self.assertEqual(events(out), [])
        self.assertEqual(states(out), [SCROLLING])

    def test_quick_click_latches(self):
        h = Harness(FULL)
        out = h.feed(press(BTN_MIDDLE), move(dy=5), release(BTN_MIDDLE))
        self.assertEqual(states(out), [SCROLLING, LATCHED])
        self.assertEqual(events(out), [])

    def test_hold_and_move_stops_on_release(self):
        h = Harness(FULL)
        out = h.feed(press(BTN_MIDDLE), move(dy=100), release(BTN_MIDDLE))
        self.assertEqual(states(out), [SCROLLING, IDLE])

    def test_pointer_frozen_while_scrolling(self):
        h = Harness(FULL)
        out = h.feed(press(BTN_MIDDLE), move(dx=40, dy=40))
        self.assertEqual(events(out), [])

    def test_any_click_ends_latched_and_is_consumed(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        out = h.feed(press(BTN_LEFT), release(BTN_LEFT))
        self.assertEqual(states(out), [IDLE])
        self.assertEqual(events(out), [])
        # the next click is normal again
        out = h.feed(press(BTN_LEFT), release(BTN_LEFT))
        self.assertEqual(events(out), [press(BTN_LEFT), release(BTN_LEFT)])

    def test_middle_click_ends_latched(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        out = h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        self.assertEqual(states(out), [IDLE])
        self.assertEqual(events(out), [])

    def test_physical_wheel_ends_latched_and_is_consumed(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        out = h.feed((EV_REL, REL_WHEEL, -1), (EV_REL, REL_WHEEL_HI_RES, -120))
        self.assertEqual(states(out), [IDLE])
        self.assertEqual(events(out), [])

    def test_other_button_while_held_is_consumed_and_does_not_end(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE))
        out = h.feed(press(BTN_RIGHT), release(BTN_RIGHT))
        self.assertEqual(events(out), [])
        self.assertEqual(states(out), [])

    def test_button_held_before_scroll_is_released_normally(self):
        h = Harness(FULL)
        h.feed(press(BTN_LEFT))
        h.feed(press(BTN_MIDDLE))
        out = h.feed(release(BTN_LEFT))
        self.assertEqual(events(out), [release(BTN_LEFT)])

    def test_mode_looked_up_once_per_press(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=3), release(BTN_MIDDLE))
        self.assertEqual(h.lookups, 1)


class HoldModeTest(unittest.TestCase):
    def test_short_click_replayed_as_middle_click(self):
        h = Harness(HOLD)
        out = h.feed(press(BTN_MIDDLE))
        self.assertEqual(events(out), [])
        out = h.feed(move(dy=4), release(BTN_MIDDLE))
        self.assertEqual(
            events(out), [press(BTN_MIDDLE), SYN, release(BTN_MIDDLE), SYN]
        )
        self.assertEqual(states(out), [])

    def test_hold_and_move_scrolls_until_release(self):
        h = Harness(HOLD)
        out = h.feed(press(BTN_MIDDLE), move(dy=30))
        self.assertEqual(states(out), [SCROLLING])
        out = h.feed(release(BTN_MIDDLE))
        self.assertEqual(states(out), [IDLE])
        self.assertEqual(events(out), [])

    def test_no_scroll_ticks_while_pending(self):
        h = Harness(HOLD)
        h.feed(press(BTN_MIDDLE), move(dy=10))
        self.assertEqual(h.tick(0.5), [])


class WheelOutputTest(unittest.TestCase):
    def test_nothing_when_idle(self):
        h = Harness(FULL)
        self.assertEqual(h.tick(0.5), [])

    def test_nothing_inside_deadzone(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=10))
        self.assertEqual(h.tick(0.5), [])

    def test_mouse_down_scrolls_down(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=300))  # ~14.5 notches/s
        out = h.run_for(0.5)
        self.assertLess(total(out, REL_WHEEL_HI_RES), -500)
        self.assertLessEqual(total(out, REL_WHEEL), -4)
        self.assertEqual(out[-1], SYN)

    def test_mouse_up_scrolls_up(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=-300))
        out = h.run_for(0.5)
        self.assertGreater(total(out, REL_WHEEL_HI_RES), 500)

    def test_mouse_right_scrolls_right(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dx=300))
        out = h.run_for(0.5)
        self.assertGreater(total(out, REL_HWHEEL_HI_RES), 500)
        self.assertGreaterEqual(total(out, REL_HWHEEL), 4)

    def test_legacy_notches_match_hires(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=60))
        out = []
        for _ in range(200):
            out += h.tick(1 / 120)
        hires = total(out, REL_WHEEL_HI_RES)
        notches = total(out, REL_WHEEL)
        self.assertEqual(notches, int(hires / 120))

    def test_latched_keeps_scrolling(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE), move(dy=300))
        self.assertTrue(h.engine.scrolling)
        self.assertLess(total(h.run_for(0.5), REL_WHEEL_HI_RES), 0)

    def test_stalled_loop_does_not_jump(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=300))  # ~14.5 notches/s
        out = h.tick(5.0)  # loop was stuck for 5 s
        self.assertGreater(total(out, REL_WHEEL_HI_RES), -2 * 120)

    def test_stops_after_release(self):
        h = Harness(FULL)
        h.feed(press(BTN_MIDDLE), move(dy=115), release(BTN_MIDDLE))
        self.assertFalse(h.engine.scrolling)
        self.assertEqual(h.tick(0.5), [])


# 1920x1080 monitor at (1000, 0); origin 100 px above its bottom edge.
SCREEN = Geometry(origin_x=1960, origin_y=979, x=1000, y=0, width=1920, height=1080)


class GeometryTest(unittest.TestCase):
    """Frozen-pointer fallback: offset from mouse movement, clamped to the screen."""

    def test_gain_converts_mouse_units_to_pixels(self):
        h = Harness(FULL, gain=0.5)
        out = h.feed(press(BTN_MIDDLE), move(dy=20), release(BTN_MIDDLE))
        self.assertEqual(states(out)[-1], LATCHED)  # 20 units = 10 px, inside 12 px
        h2 = Harness(FULL, gain=0.5)
        out = h2.feed(press(BTN_MIDDLE), move(dy=40), release(BTN_MIDDLE))
        self.assertEqual(states(out)[-1], IDLE)  # 40 units = 20 px: a hold

    def test_virtual_pointer_stops_at_screen_edge(self):
        h = Harness(FULL, geometry=SCREEN, free_pointer=False)
        h.feed(press(BTN_MIDDLE), move(dy=5000))
        out = h.run_for(0.5)  # at the edge: max speed, 250 notches/s
        self.assertLess(total(out, REL_WHEEL), -120)

    def test_edge_zone_boosts_speed(self):
        plain = Harness(FULL)
        edged = Harness(FULL, geometry=SCREEN, free_pointer=False)
        for h in (plain, edged):
            h.feed(press(BTN_MIDDLE), move(dy=90))  # 10 px from the bottom edge
        self.assertLess(
            total(edged.run_for(0.5), REL_WHEEL_HI_RES),
            2 * total(plain.run_for(0.5), REL_WHEEL_HI_RES),
        )

    def test_away_from_edge_uses_main_zone(self):
        plain = Harness(FULL)
        edged = Harness(FULL, geometry=SCREEN, free_pointer=False)
        for h in (plain, edged):
            h.feed(press(BTN_MIDDLE), move(dy=-300))  # upwards, far from the top
        self.assertEqual(
            total(edged.run_for(0.5), REL_WHEEL_HI_RES),
            total(plain.run_for(0.5), REL_WHEEL_HI_RES),
        )

    def test_geometry_looked_up_once_per_scroll(self):
        h = Harness(FULL, geometry=SCREEN, free_pointer=False)
        h.feed(press(BTN_MIDDLE), move(dy=30), move(dy=30), release(BTN_MIDDLE))
        self.assertEqual(h.geometry_lookups, 1)

    def test_geometry_not_looked_up_for_ignored_windows(self):
        h = Harness(IGNORE, geometry=SCREEN, free_pointer=False)
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        self.assertEqual(h.geometry_lookups, 0)


TASK_DOWN = (EV_KEY, BTN_TASK, 1)
TASK_UP = (EV_KEY, BTN_TASK, 0)


class FreePointerTest(unittest.TestCase):
    """Pointer moves freely, like Zen; BTN_TASK held on the clone keeps the
    scroll on the window where it started; speed comes from the real pointer."""

    def h(self, mode=FULL):
        return Harness(mode, geometry=SCREEN)

    def test_start_holds_task_button(self):
        out = self.h().feed(press(BTN_MIDDLE))
        self.assertEqual(events(out), [TASK_DOWN, SYN])
        self.assertEqual(states(out), [SCROLLING])

    def test_motion_forwarded_while_scrolling(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        self.assertEqual(events(h.feed(move(dx=40))), [(EV_REL, REL_X, 40)])

    def test_click_hold_split_still_from_mouse_movement(self):
        out = self.h().feed(press(BTN_MIDDLE), move(dy=5), release(BTN_MIDDLE))
        self.assertEqual(states(out)[-1], LATCHED)
        self.assertNotIn(TASK_UP, events(out))  # latched keeps the grab

    def test_hold_release_lets_go_of_task_button(self):
        out = self.h().feed(press(BTN_MIDDLE), move(dy=100), release(BTN_MIDDLE))
        self.assertEqual(states(out)[-1], IDLE)
        self.assertEqual(events(out)[-2:], [TASK_UP, SYN])

    def test_latched_exit_click_consumed_and_task_released(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE), release(BTN_MIDDLE))
        out = h.feed(press(BTN_LEFT), release(BTN_LEFT))
        self.assertEqual(events(out), [TASK_UP, SYN])
        self.assertEqual(states(out), [IDLE])

    def test_speed_from_real_pointer(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        out = h.run_for(0.5, pointer=(1960, 979 - 300))  # 300 px up: ~14.5 notches/s
        self.assertGreater(total(out, REL_WHEEL_HI_RES), 500)

    def test_pointer_unknown_keeps_last_offset(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        h.tick(1 / 120, pointer=(1960, 679))
        out = h.run_for(0.5)  # Hyprland didn't answer
        self.assertGreater(total(out, REL_WHEEL_HI_RES), 500)

    def test_pointer_on_another_monitor_is_clamped_to_edge(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        out = h.run_for(0.5, pointer=(1960, 5000))  # past the bottom edge: max speed
        self.assertLess(total(out, REL_WHEEL), -120)

    def test_hold_mode_short_click_has_no_task_button(self):
        out = self.h(HOLD).feed(press(BTN_MIDDLE), move(dy=3), release(BTN_MIDDLE))
        self.assertNotIn(TASK_DOWN, events(out))
        self.assertIn(press(BTN_MIDDLE), events(out))

    def test_hold_mode_scroll_holds_task_button(self):
        out = self.h(HOLD).feed(press(BTN_MIDDLE), move(dy=40))
        self.assertIn(TASK_DOWN, events(out))

    def test_disabled_freezes_pointer(self):
        h = Harness(FULL, geometry=SCREEN, free_pointer=False)
        out = h.feed(press(BTN_MIDDLE), move(dx=40))
        self.assertEqual(events(out), [])

    def test_no_geometry_freezes_pointer(self):
        out = Harness(FULL).feed(press(BTN_MIDDLE), move(dx=40))
        self.assertEqual(events(out), [])

    def test_offset_reports_pointer_distance(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        h.tick(1 / 120, pointer=(1960 + 10, 979 - 40))
        self.assertEqual(h.engine.offset, (10, -40))

    def test_shutdown_releases_task_button(self):
        h = self.h()
        h.feed(press(BTN_MIDDLE))
        self.assertEqual(h.engine.shutdown(), [TASK_UP, SYN])


class ShutdownTest(unittest.TestCase):
    def test_releases_buttons_held_on_clone(self):
        h = Harness(FULL)
        h.feed(press(BTN_LEFT))
        self.assertEqual(h.engine.shutdown(), [release(BTN_LEFT), SYN])

    def test_nothing_to_release(self):
        h = Harness(FULL)
        h.feed(press(BTN_LEFT), release(BTN_LEFT))
        self.assertEqual(h.engine.shutdown(), [])


if __name__ == "__main__":
    unittest.main()
