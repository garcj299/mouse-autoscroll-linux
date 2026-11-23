import tempfile
import unittest
from pathlib import Path

from mouse_autoscroll.config import DEFAULTS, load
from mouse_autoscroll.modes import FULL, HOLD, IGNORE


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    f.write(text)
    f.close()
    return Path(f.name)


class ConfigTest(unittest.TestCase):
    def test_missing_file_gives_defaults_silently(self):
        cfg, warnings = load(Path("/nonexistent/config.toml"))
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(warnings, [])

    def test_default_app_list(self):
        self.assertEqual(DEFAULTS.rules.mode_for("zen"), IGNORE)
        self.assertEqual(DEFAULTS.rules.mode_for("steam_app_42"), IGNORE)
        self.assertEqual(DEFAULTS.rules.mode_for("kitty"), HOLD)
        self.assertEqual(DEFAULTS.rules.mode_for("md.obsidian.Obsidian"), HOLD)
        self.assertEqual(DEFAULTS.rules.mode_for("libreoffice-writer"), FULL)

    def test_overrides(self):
        cfg, warnings = load(
            write('[scroll]\ndeadzone = 30\n[apps]\nhold = ["foot"]\n')
        )
        self.assertEqual(warnings, [])
        self.assertEqual(cfg.curve.deadzone, 30)
        self.assertEqual(cfg.curve.slope, DEFAULTS.curve.slope)
        self.assertEqual(cfg.rules.mode_for("foot"), HOLD)
        self.assertEqual(cfg.rules.mode_for("kitty"), FULL)  # list replaced
        self.assertEqual(cfg.rules.mode_for("zen"), IGNORE)  # untouched list

    def test_broken_toml_gives_defaults_and_warning(self):
        cfg, warnings = load(write("[scroll\ndeadzone = "))
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(len(warnings), 1)

    def test_wrong_type_keeps_default_and_warns(self):
        cfg, warnings = load(write('[scroll]\ndeadzone = "big"\nexponent = 2\n'))
        self.assertEqual(cfg.curve.deadzone, DEFAULTS.curve.deadzone)
        self.assertEqual(cfg.curve.exponent, 2)
        self.assertEqual(len(warnings), 1)

    def test_bad_app_list_keeps_default_and_warns(self):
        cfg, warnings = load(write('[apps]\nhold = "kitty"\n'))
        self.assertEqual(cfg.rules.hold, DEFAULTS.rules.hold)
        self.assertEqual(len(warnings), 1)

    def test_new_keys(self):
        cfg, warnings = load(
            write("[scroll]\nsensitivity = 1.5\nmin_speed = 2\nslope = 0.01\nedge_zone = 0.1\n")
        )
        self.assertEqual(warnings, [])
        self.assertEqual(cfg.curve.sensitivity, 1.5)
        self.assertEqual(cfg.curve.min_speed, 2)
        self.assertEqual(cfg.curve.slope, 0.01)
        self.assertEqual(cfg.curve.edge_zone, 0.1)

    def test_edge_zone_out_of_range_rejected(self):
        cfg, warnings = load(write("[scroll]\nedge_zone = 0.9\n"))
        self.assertEqual(cfg.curve.edge_zone, DEFAULTS.curve.edge_zone)
        self.assertEqual(len(warnings), 1)

    def test_edge_zone_zero_disables_it(self):
        cfg, warnings = load(write("[scroll]\nedge_zone = 0\n"))
        self.assertEqual(warnings, [])
        self.assertEqual(cfg.curve.edge_zone, 0)

    def test_free_pointer_default_on(self):
        self.assertTrue(DEFAULTS.free_pointer)

    def test_free_pointer_can_be_turned_off(self):
        cfg, warnings = load(write("[scroll]\nfree_pointer = false\n"))
        self.assertEqual(warnings, [])
        self.assertFalse(cfg.free_pointer)

    def test_free_pointer_must_be_bool(self):
        cfg, warnings = load(write("[scroll]\nfree_pointer = 0\n"))
        self.assertTrue(cfg.free_pointer)
        self.assertEqual(len(warnings), 1)

    def test_removed_gain_key_warns(self):
        cfg, warnings = load(write("[scroll]\ngain = 0.8\n"))
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(len(warnings), 1)

    def test_old_key_warns(self):
        cfg, warnings = load(write("[scroll]\nspeed = 0.01\n"))
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(len(warnings), 1)

    def test_nonpositive_numbers_rejected(self):
        cfg, warnings = load(write("[scroll]\ntick_hz = 0\nmax_speed = -1\n"))
        self.assertEqual(cfg.tick_hz, DEFAULTS.tick_hz)
        self.assertEqual(cfg.curve.max_speed, DEFAULTS.curve.max_speed)
        self.assertEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
