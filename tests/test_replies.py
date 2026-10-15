import unittest
from unittest.mock import MagicMock
import discord
from utils.messages import format_reply_context, _collect


class DummyAuthor:
    def __init__(self, display_name: str, author_id: int = 100):
        self.display_name = display_name
        self.id = author_id

    def __str__(self):
        return self.display_name


class DummyReference:
    def __init__(self, message_id=None, resolved=None, ref_type=None):
        self.message_id = message_id
        self.resolved = resolved
        self.type = ref_type


class DummyMessage:
    def __init__(self, author, clean_content, reference=None, msg_id=1, reactions=None):
        self.id = msg_id
        self.author = author
        self.clean_content = clean_content
        self.reference = reference
        self.reactions = reactions or []


class TestRepliesFormatting(unittest.IsolatedAsyncioTestCase):
    async def test_no_reference(self):
        msg = DummyMessage(DummyAuthor("Alice"), "Hello world")
        res = await format_reply_context(msg, "Alice", {})
        self.assertEqual(res, "")

    async def test_reply_to_other_author_resolved(self):
        parent_msg = DummyMessage(DummyAuthor("Alice"), "Should we push to prod?")
        reply_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Definitely not",
            reference=DummyReference(resolved=parent_msg),
        )
        res = await format_reply_context(reply_msg, "Bob", {})
        self.assertEqual(res, '[replying to Alice: "Should we push to prod?"]')

    async def test_reply_to_self(self):
        parent_msg = DummyMessage(DummyAuthor("Alice"), "Meet at 2pm")
        reply_msg = DummyMessage(
            DummyAuthor("Alice"),
            "Wait actually 3pm",
            reference=DummyReference(resolved=parent_msg),
        )
        res = await format_reply_context(reply_msg, "Alice", {})
        self.assertEqual(res, '[replying to self: "Meet at 2pm"]')

    async def test_forward_message(self):
        parent_msg = DummyMessage(DummyAuthor("Alice"), "Important announcement")
        forward_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Check this out",
            reference=DummyReference(
                resolved=parent_msg,
                ref_type=discord.MessageReferenceType.forward,
            ),
        )
        res = await format_reply_context(forward_msg, "Bob", {})
        self.assertEqual(res, "[Forwarded from Alice]")

    async def test_snippet_truncation(self):
        long_text = "This is a very long message that should definitely be truncated before sending to LLM context"
        parent_msg = DummyMessage(DummyAuthor("Alice"), long_text)
        reply_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Got it",
            reference=DummyReference(resolved=parent_msg),
        )
        res = await format_reply_context(reply_msg, "Bob", {}, max_snippet_len=40)
        # Length of snippet should be at most 40 chars
        self.assertIn("...", res)
        # res looks like: [replying to Alice: "<snippet>..."]
        snippet = res.split(': "')[1].rstrip('"]')
        self.assertTrue(len(snippet) <= 40)

    async def test_snippet_quotes_sanitization(self):
        parent_msg = DummyMessage(DummyAuthor("Alice"), 'She said "hello" to everyone')
        reply_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Indeed",
            reference=DummyReference(resolved=parent_msg),
        )
        res = await format_reply_context(reply_msg, "Bob", {})
        self.assertEqual(res, "[replying to Alice: \"She said 'hello' to everyone\"]")

    async def test_fallback_to_seen_messages_cache(self):
        reply_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Agreed",
            reference=DummyReference(message_id=42, resolved=None),
        )
        seen = {42: ("Charlie", "Let's order pizza")}
        res = await format_reply_context(reply_msg, "Bob", seen)
        self.assertEqual(res, '[replying to Charlie: "Let\'s order pizza"]')

    async def test_fallback_to_earlier_message_when_unresolved(self):
        reply_msg = DummyMessage(
            DummyAuthor("Bob"),
            "Agreed",
            reference=DummyReference(message_id=999, resolved=None),
        )
        res = await format_reply_context(reply_msg, "Bob", {})
        self.assertEqual(res, "[replying to earlier message]")


class TestRepliesCollectorIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_collect_threads_and_replies(self):
        channel = MagicMock()
        channel.id = 1234
        channel.guild = None

        # Thread:
        # 1. Alice: Should we deploy today?
        # 2. Bob [replying to Alice: "Should we deploy today?"]: No wait
        # 3. Bob: I see a critical bug
        # 4. Alice [replying to self: "Should we deploy today?"]: Okay pausing release
        m1 = MagicMock()
        m1.id = 1
        m1.author.bot = False
        m1.author.id = 101
        m1.author.display_name = "Alice"
        m1.clean_content = "Should we deploy today?"
        m1.reference = None
        m1.reactions = []

        m2 = MagicMock()
        m2.id = 2
        m2.author.bot = False
        m2.author.id = 102
        m2.author.display_name = "Bob"
        m2.clean_content = "No wait"
        m2.reference = DummyReference(message_id=1, resolved=m1)
        m2.reactions = []

        m3 = MagicMock()
        m3.id = 3
        m3.author.bot = False
        m3.author.id = 102
        m3.author.display_name = "Bob"
        m3.clean_content = "I see a critical bug"
        m3.reference = None
        m3.reactions = []

        m4 = MagicMock()
        m4.id = 4
        m4.author.bot = False
        m4.author.id = 101
        m4.author.display_name = "Alice"
        m4.clean_content = "Okay pausing release"
        m4.reference = DummyReference(message_id=1, resolved=m1)
        m4.reactions = []

        async def async_history(*args, **kwargs):
            for m in [m1, m2, m3, m4]:
                yield m

        channel.history = async_history

        messages, truncated = await _collect(channel)
        self.assertFalse(truncated)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0], "1. Alice: Should we deploy today?")
        self.assertEqual(messages[1], '2. Bob [replying to Alice: "Should we deploy today?"]: No wait')
        self.assertEqual(messages[2], "3. Bob: I see a critical bug")
        self.assertEqual(messages[3], '4. Alice [replying to self: "Should we deploy today?"]: Okay pausing release')


if __name__ == "__main__":
    unittest.main()
