import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
from engagement import classify, normalize


class EngagementTests(unittest.TestCase):
    def test_normalizes_unicode_and_whitespace(self):
        self.assertEqual(normalize("  HELLO\u200b   There  "), "hello there")

    def test_rejects_noise(self):
        cases = [
            (None, True, "non_text"),
            ("😀🔥", False, "emoji_or_punctuation_only"),
            ("Good morning!", False, "greeting_only"),
            ("Click https://example.com for my discount", False, "promotional_spam"),
            ("yes okay", False, "too_short"),
        ]
        for text, media, reason in cases:
            with self.subTest(text=text):
                self.assertEqual(classify(text, media=media).reason, reason)

    def test_accepts_meaningful_and_rejects_repeat(self):
        text = "I loved the discussion about scheduling our next community event"
        first = classify(text)
        self.assertTrue(first.accepted)
        second = classify(text, is_repeat=lambda digest, since: digest == first.digest)
        self.assertEqual(second.reason, "repeated_text")

    def test_punctuation_changes_do_not_bypass_repeat_filter(self):
        first = classify("This is a genuinely useful contribution to our discussion")
        second = classify(
            "This is a genuinely useful contribution to our discussion!!!",
            is_repeat=lambda digest, since: digest == first.digest,
        )
        self.assertEqual(second.reason, "repeated_text")


if __name__ == "__main__": unittest.main()
