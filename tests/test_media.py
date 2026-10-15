import unittest
from unittest.mock import MagicMock
from utils.messages import enrich_content, format_gif_slug, _collect


class DummyAttachment:
    def __init__(self, filename: str):
        self.filename = filename


class DummySticker:
    def __init__(self, name: str):
        self.name = name


class TestMediaAndGifs(unittest.TestCase):
    def test_tenor_url_parsing(self):
        url = "https://tenor.com/view/shocked-cat-falling-gif-20518742"
        res = enrich_content(url)
        self.assertEqual(res, "[GIF: shocked cat falling]")

    def test_giphy_url_parsing(self):
        url = "https://giphy.com/gifs/the-office-no-steve-carell-5xtDarzp5at2qwSTYoo"
        res = enrich_content(url)
        self.assertEqual(res, "[GIF: the office no steve carell]")

    def test_text_with_embedded_gif_url(self):
        msg = "Look at this cat: https://tenor.com/view/funny-cat-dancing-gif-12345 haha"
        res = enrich_content(msg)
        self.assertEqual(res, "Look at this cat: [GIF: funny cat dancing] haha")

    def test_gif_attachment_without_text(self):
        attachments = [DummyAttachment("party_blob.gif")]
        res = enrich_content("", attachments=attachments)
        self.assertEqual(res, "[GIF: party_blob.gif]")

    def test_image_attachment_without_text(self):
        attachments = [DummyAttachment("architecture_diagram.png")]
        res = enrich_content("", attachments=attachments)
        self.assertEqual(res, "[Image: architecture_diagram.png]")

    def test_other_attachment(self):
        attachments = [DummyAttachment("report.pdf")]
        res = enrich_content("", attachments=attachments)
        self.assertEqual(res, "[Attachment: report.pdf]")

    def test_sticker_without_text(self):
        stickers = [DummySticker("Pepe Clap")]
        res = enrich_content("", stickers=stickers)
        self.assertEqual(res, "[Sticker: Pepe Clap]")

    def test_text_with_attachments_and_stickers(self):
        res = enrich_content(
            "here are the logs",
            attachments=[DummyAttachment("error.png")],
            stickers=[DummySticker("Facepalm")],
        )
        self.assertEqual(res, "here are the logs [Sticker: Facepalm] [Image: error.png]")

    def test_empty_content_remains_empty(self):
        res = enrich_content("")
        self.assertEqual(res, "")

    def test_media_capping(self):
        attachments = [DummyAttachment(f"img_{i}.png") for i in range(5)]
        res = enrich_content("", attachments=attachments, max_media=3)
        self.assertIn("[Image: img_0.png]", res)
        self.assertIn("[Image: img_2.png]", res)
        self.assertIn("[+2 more files]", res)
        self.assertNotIn("img_3.png", res)


class TestMediaCollectorIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_collect_preserves_media_messages(self):
        channel = MagicMock()
        channel.id = 8888
        channel.guild = None

        # Message 1: GIF sent via Tenor URL
        m1 = MagicMock()
        m1.id = 1
        m1.author.bot = False
        m1.author.id = 101
        m1.author.display_name = "Alice"
        m1.clean_content = "https://tenor.com/view/confused-john-travolta-what-huh-gif-14811776"
        m1.attachments = []
        m1.stickers = []
        m1.reference = None
        m1.reactions = []

        # Message 2: Bob replies to Alice's GIF with a reaction
        m2 = MagicMock()
        m2.id = 2
        m2.author.bot = False
        m2.author.id = 102
        m2.author.display_name = "Bob"
        m2.clean_content = "same here"
        m2.attachments = []
        m2.stickers = []
        # Message reference pointing to m1
        ref = MagicMock()
        ref.type = None
        ref.message_id = 1
        ref.resolved = m1
        m2.reference = ref
        rx = MagicMock()
        rx.count = 4
        rx.emoji = "😂"
        m2.reactions = [rx]

        # Message 3: Charlie posts an attached GIF without text
        m3 = MagicMock()
        m3.id = 3
        m3.author.bot = False
        m3.author.id = 103
        m3.author.display_name = "Charlie"
        m3.clean_content = ""
        m3.attachments = [DummyAttachment("laughing.gif")]
        m3.stickers = []
        m3.reference = None
        m3.reactions = []

        async def async_history(*args, **kwargs):
            for m in [m1, m2, m3]:
                yield m

        channel.history = async_history

        messages, truncated = await _collect(channel)
        self.assertFalse(truncated)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0], "1. Alice: [GIF: confused john travolta what huh]")
        self.assertEqual(
            messages[1],
            '2. Bob [replying to Alice: "[GIF: confused john travolta what huh]"]: same here [Reactions: 😂x4]'
        )
        self.assertEqual(messages[2], "3. Charlie: [GIF: laughing.gif]")


if __name__ == "__main__":
    unittest.main()
