import unittest

from mouse_autoscroll.modes import FULL, HOLD, IGNORE, ModeRules


RULES = ModeRules(
    ignore=["zen", "firefox", "steam_app_*"],
    hold=["kitty", "*obsidian*"],
)


class ModeRulesTest(unittest.TestCase):
    def test_unlisted_class_is_full(self):
        self.assertEqual(RULES.mode_for("libreoffice-writer"), FULL)

    def test_exact_ignore(self):
        self.assertEqual(RULES.mode_for("zen"), IGNORE)

    def test_glob_ignore(self):
        self.assertEqual(RULES.mode_for("steam_app_1091500"), IGNORE)

    def test_hold(self):
        self.assertEqual(RULES.mode_for("kitty"), HOLD)

    def test_case_insensitive_glob(self):
        self.assertEqual(RULES.mode_for("md.obsidian.Obsidian"), HOLD)

    def test_unknown_window_is_full(self):
        self.assertEqual(RULES.mode_for(None), FULL)
        self.assertEqual(RULES.mode_for(""), FULL)

    def test_ignore_wins_over_hold(self):
        rules = ModeRules(ignore=["kitty"], hold=["kitty"])
        self.assertEqual(rules.mode_for("kitty"), IGNORE)


if __name__ == "__main__":
    unittest.main()
