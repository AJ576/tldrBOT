import unittest
from unittest.mock import MagicMock, AsyncMock
from utils.messages import format_reactions, _collect


class DummyEmoji:
    def __init__(self, name: str, emoji_id: int):
        self.name = name
        self.id = emoji_id

    def __str__(self):
        return f"<:{self.name}:{self.id}>"


class DummyReaction:
    def __init__(self, emoji, count: int):
        self.emoji = emoji
        self.count = count


class TestReactionsFormatting(unittest.TestCase):
    def test_none_or_empty_reactions(self):
        self.assertEqual(format_reactions(None), "")
        self.assertEqual(format_reactions([]), "")

    def test_zero_count_reactions(self):
        reactions = [
            DummyReaction("👍", 0),
            DummyReaction("🔥", -1),
        ]
        self.assertEqual(format_reactions(reactions), "")

    def test_unicode_reactions_sorted_by_count(self):
        reactions = [
            DummyReaction("👍", 2),
            DummyReaction("💀", 10),
            DummyReaction("🎉", 5),
        ]
        # Should be sorted: 💀 (10), 🎉 (5), 👍 (2)
        result = format_reactions(reactions)
        self.assertEqual(result, " [Reactions: 💀x10, 🎉x5, 👍x2]")

    def test_custom_emoji_uses_name_not_id(self):
        custom = DummyEmoji("cat_jam", 123456789)
        reactions = [
            DummyReaction(custom, 4),
            DummyReaction("❤️", 1),
        ]
        result = format_reactions(reactions)
        # Verify it uses :cat_jam: rather than <:cat_jam:123456789>
        self.assertIn(":cat_jam:x4", result)
        self.assertNotIn("123456789", result)
        self.assertEqual(result, " [Reactions: :cat_jam:x4, ❤️x1]")

    def test_caps_at_max_reactions(self):
        reactions = [
            DummyReaction(f"emoji_{i}", i) for i in range(1, 10)
        ]
        # counts 1 to 9. Top 5: emoji_9 (9) down to emoji_5 (5)
        result = format_reactions(reactions, max_reactions=5)
        self.assertIn("emoji_9x9", result)
        self.assertIn("emoji_5x5", result)
        self.assertNotIn("emoji_4x4", result)
        self.assertNotIn("emoji_1x1", result)


class TestReactionsCollectorIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_collect_includes_reactions(self):
        channel = MagicMock()
        channel.id = 999
        channel.guild = None

        msg1 = MagicMock()
        msg1.id = 1
        msg1.author.bot = False
        msg1.author.id = 101
        msg1.author.display_name = "Alice"
        msg1.clean_content = "Should we deploy today?"
        msg1.reactions = [
            DummyReaction("💀", 5),
            DummyReaction("👍", 2),
        ]
        msg1.reference = None

        msg2 = MagicMock()
        msg2.id = 2
        msg2.author.bot = False
        msg2.author.id = 102
        msg2.author.display_name = "Bob"
        msg2.clean_content = "No wait"
        msg2.reactions = []
        msg2.reference = None

        async def async_history(*args, **kwargs):
            yield msg1
            yield msg2

        channel.history = async_history

        messages, truncated = await _collect(channel)
        self.assertFalse(truncated)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], "1. Alice: Should we deploy today? [Reactions: 💀x5, 👍x2]")
        self.assertEqual(messages[1], "2. Bob: No wait")


if __name__ == "__main__":
    unittest.main()
