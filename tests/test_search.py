import unittest

from quickdesk.commands import Command, CommandType
from quickdesk.search import score_command, search, tokenize


def make(name, description="", type_=CommandType.APP, id_=None):
    return Command(id_ or name.lower(), name, description, type_, "target")


COMMANDS = [
    make("Notepad", "Windows text editor"),
    make("Calculator", "Windows calculator"),
    make("Paint", "Windows drawing program"),
    make("Downloads", "Your Downloads folder", CommandType.PATH),
    make("GitHub", "Code hosting and collaboration", CommandType.URL),
    make("YouTube", "Video hosting", CommandType.URL),
]


def names(commands):
    return [command.name for command in commands]


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_drops_punctuation(self):
        self.assertEqual(tokenize("  Hello, WORLD!  "), ["hello", "world"])

    def test_keeps_cyrillic_words(self):
        self.assertEqual(tokenize("Блокнот Windows"), ["блокнот", "windows"])


class SearchTests(unittest.TestCase):
    def test_empty_query_returns_all_in_original_order(self):
        self.assertEqual(search("   ", COMMANDS), COMMANDS)

    def test_search_ignores_case(self):
        for query in ("notepad", "NOTEPAD", "NoTePaD"):
            with self.subTest(query=query):
                self.assertEqual(names(search(query, COMMANDS))[0], "Notepad")

    def test_partial_match_at_start_of_name(self):
        self.assertEqual(names(search("calc", COMMANDS)), ["Calculator"])

    def test_partial_match_inside_word(self):
        self.assertIn("GitHub", names(search("hub", COMMANDS)))

    def test_searches_description(self):
        self.assertEqual(names(search("drawing", COMMANDS)), ["Paint"])

    def test_searches_category(self):
        self.assertEqual(names(search("website", COMMANDS)), ["GitHub", "YouTube"])
        self.assertEqual(names(search("folder", COMMANDS)), ["Downloads"])

    def test_name_match_ranks_above_description_match(self):
        commands = [
            make("Text tools", "Utilities", id_="a"),
            make("Notes", "Simple text editor", id_="b"),
        ]
        self.assertEqual(names(search("text", commands)), ["Text tools", "Notes"])

    def test_exact_name_ranks_above_prefix(self):
        commands = [make("Paint 3D", id_="a"), make("Paint", id_="b"), make("Paintbrush", id_="c")]
        self.assertEqual(names(search("paint", commands))[0], "Paint")

    def test_prefix_ranks_above_substring(self):
        commands = [make("YouTube", id_="a"), make("Tubes", id_="b")]
        self.assertEqual(names(search("tube", commands)), ["Tubes", "YouTube"])

    def test_all_query_words_must_match(self):
        self.assertEqual(names(search("windows calculator", COMMANDS)), ["Calculator"])
        self.assertEqual(search("windows youtube", COMMANDS), [])

    def test_tolerates_simple_typos(self):
        self.assertEqual(names(search("notpad", COMMANDS))[0], "Notepad")
        self.assertEqual(names(search("calcualtor", COMMANDS))[0], "Calculator")
        self.assertEqual(names(search("gihtub", COMMANDS))[0], "GitHub")

    def test_short_queries_are_not_fuzzy(self):
        # "pzt" is not close enough to anything and must not match.
        self.assertEqual(search("pzt", COMMANDS), [])

    def test_no_match_returns_empty_list(self):
        self.assertEqual(search("spreadsheet", COMMANDS), [])

    def test_equal_scores_are_sorted_by_name(self):
        commands = [make("Zeta", "tool", id_="z"), make("Alpha", "tool", id_="a")]
        self.assertEqual(names(search("tool", commands)), ["Alpha", "Zeta"])

    def test_score_is_zero_for_empty_query(self):
        self.assertEqual(score_command("", COMMANDS[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
