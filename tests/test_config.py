import unittest

from app.config import _clean_env_value


class EnvParsingTests(unittest.TestCase):
    def test_strips_inline_comment_after_quoted_value(self):
        self.assertEqual(
            _clean_env_value('"openai" # it can be easyocr or openai'),
            "openai",
        )

    def test_strips_inline_comment_after_unquoted_value(self):
        self.assertEqual(_clean_env_value("easyocr # default"), "easyocr")


if __name__ == "__main__":
    unittest.main()

