import unittest

import md_viewer


class TuiSearchTests(unittest.TestCase):
    def test_hotkeys_work_with_russian_layout_and_caps_lock(self):
        variants = {
            "q": ("q", "Q", "й", "Й"),
            "k": ("k", "K", "л", "Л"),
            "j": ("j", "J", "о", "О"),
            "r": ("r", "R", "к", "К"),
            "b": ("b", "B", "и", "И"),
            "n": ("n", "N", "т", "Т"),
            "p": ("p", "P", "з", "З"),
            "/": ("/", "."),
        }

        for expected, keys in variants.items():
            for key in keys:
                with self.subTest(expected=expected, key=key):
                    self.assertEqual(md_viewer.tui_hotkey(key), expected)

    def test_non_character_keys_are_unchanged(self):
        self.assertEqual(md_viewer.tui_hotkey(md_viewer.curses.KEY_DOWN), md_viewer.curses.KEY_DOWN)

    def test_f7_and_slash_open_search(self):
        self.assertTrue(md_viewer.tui_is_search_key(md_viewer.curses.KEY_F7))
        self.assertTrue(md_viewer.tui_is_search_key("/"))
        self.assertTrue(md_viewer.tui_is_search_key("."))
        self.assertFalse(md_viewer.tui_is_search_key("n"))

    def test_search_status_keeps_document_hotkeys(self):
        status = md_viewer.tui_document_status("ip", 6, 4)

        self.assertEqual(
            status,
            "↑↓ PgUp/PgDn | ←→ горизонтально | Поиск /ip [5/6] | "
            "n следующее | p предыдущее | F7 новый поиск | "
            "Home/End | r обновить | b список | q выход",
        )

        self.assertIn("F7 поиск", md_viewer.tui_document_status())

    def test_find_matches_is_literal_and_case_insensitive(self):
        lines = ["Alpha alpha", "a.* is literal", "nothing"]

        self.assertEqual(
            md_viewer.tui_find_matches(lines, "alpha"),
            [(0, 0, 5), (0, 6, 11)],
        )
        self.assertEqual(md_viewer.tui_find_matches(lines, "a.*"), [(1, 0, 3)])

    def test_empty_query_has_no_matches(self):
        self.assertEqual(md_viewer.tui_find_matches(["text"], ""), [])

    def test_initial_match_starts_at_current_scroll_and_wraps(self):
        matches = [(1, 0, 2), (4, 3, 5), (8, 0, 2)]

        self.assertEqual(md_viewer.tui_initial_match(matches, 4), 1)
        self.assertEqual(md_viewer.tui_initial_match(matches, 9), 0)

    def test_move_match_visits_each_match_including_same_line(self):
        matches = [(1, 0, 2), (1, 4, 6), (4, 3, 5), (4, 8, 10)]

        self.assertEqual(md_viewer.tui_move_match(matches, 0, 1), 1)
        self.assertEqual(md_viewer.tui_move_match(matches, 2, -1), 1)

    def test_move_match_wraps_and_stays_when_only_one_line_matches(self):
        matches = [(1, 0, 2), (1, 4, 6), (4, 3, 5)]

        self.assertEqual(md_viewer.tui_move_match(matches, 2, 1), 0)
        self.assertEqual(md_viewer.tui_move_match(matches, 0, -1), 2)
        self.assertEqual(md_viewer.tui_move_match(matches[:2], 0, 1), 1)
        self.assertEqual(md_viewer.tui_move_match([], 0, 1), 0)

    def test_max_scroll_keeps_last_page_filled(self):
        self.assertEqual(md_viewer.tui_max_scroll(100, 24), 78)
        self.assertEqual(md_viewer.tui_max_scroll(10, 24), 0)

    def test_render_search_line_inverts_every_visible_match(self):
        class Window:
            def __init__(self):
                self.writes = []

            def getmaxyx(self):
                return 3, 40

            def addnstr(self, y, x, text, size, attr):
                self.writes.append((y, x, text[:size], attr))

        window = Window()
        md_viewer.tui_render_search_line(
            window,
            1,
            "one needle, two needle",
            0,
            [(4, 10), (16, 22)],
        )

        highlighted = [text for _, _, text, attr in window.writes if attr & md_viewer.curses.A_REVERSE]
        self.assertEqual(highlighted, ["needle", "needle"])


if __name__ == "__main__":
    unittest.main()
