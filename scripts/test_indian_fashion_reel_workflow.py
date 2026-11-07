import sys
import unittest
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.gemini_client import GeminiClient
from app.chatgpt_client import ChatGPTClient, GeneratedScript
from app.caption_generator import CaptionGenerator
from app.browser_manager import BrowserManager

class TestIndianFashionReelWorkflow(unittest.TestCase):
    """Verifies the new Indian fashion + dance workflow end-to-end logic."""

    @classmethod
    def setUpClass(cls):
        cls.config_mgr = ConfigurationManager()
        cls.config = cls.config_mgr.config

    def test_1_gemini_topic_schema_validation(self):
        """Validates Gemini fashion & song topic validation logic."""
        valid_sample = {
            "trend_date": "2026-10-18",
            "song_name": "Tauba Tauba",
            "artist": "Karan Aujla",
            "trend_evidence": "Viral hook step across millions of Instagram Reels and music charts.",
            "source_urls": ["https://www.billboard.com/charts/india-songs-hotw"],
            "outfit_concept": "High-waist wide-leg distressed denim jeans paired with a cropped ribbed white tank top and sleek white sneakers.",
            "dance_style": "Fast-paced footwork with energetic, sharp arm hooks synchronized to the bass drop.",
            "visual_theme": "Modern minimalist studio with warm golden accent lighting and gentle continuous tracking shot.",
            "video_prompt_requirements": "Photorealistic 9:16 vertical 10-second video of an adult Indian woman (age 22) dancing."
        }
        valid, msg = GeminiClient.validate_topic_data(valid_sample)
        self.assertTrue(valid, f"Validation failed for valid sample: {msg}")

        # Invalid: missing song_name
        invalid_sample_1 = dict(valid_sample)
        del invalid_sample_1["song_name"]
        valid1, msg1 = GeminiClient.validate_topic_data(invalid_sample_1)
        self.assertFalse(valid1)
        self.assertIn("song_name", msg1)

        # Invalid: missing outfit_concept
        invalid_sample_2 = dict(valid_sample)
        del invalid_sample_2["outfit_concept"]
        valid2, msg2 = GeminiClient.validate_topic_data(invalid_sample_2)
        self.assertFalse(valid2)
        self.assertIn("outfit_concept", msg2)

        # Invalid: invalid source URL
        invalid_sample_3 = dict(valid_sample)
        invalid_sample_3["source_urls"] = ["not-a-valid-url"]
        valid3, msg3 = GeminiClient.validate_topic_data(invalid_sample_3)
        self.assertFalse(valid3)
        self.assertIn("valid web URLs", msg3)

    def test_2_gemini_json_parsing_with_code_fences(self):
        """Verifies Gemini response parser correctly strips fences and labels."""
        raw_response = (
            "Here is the trending topic you requested:\n\n"
            "```json\n"
            "{\n"
            '  "song_name": "Chaleya",\n'
            '  "artist": "Arijit Singh, Shilpa Rao",\n'
            '  "outfit_concept": "Chic pastel co-ord set with oversized blazer and chunky sneakers",\n'
            '  "dance_style": "Fluid contemporary Bollywood lyrical routine",\n'
            '  "source_urls": ["https://open.spotify.com/charts"]\n'
            "}\n"
            "```\n\nHope this helps!"
        )
        parsed = GeminiClient._parse_json(raw_response)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("song_name"), "Chaleya")
        self.assertEqual(parsed.get("artist"), "Arijit Singh, Shilpa Rao")

    def test_3_chatgpt_script_schema_parsing(self):
        """Validates ChatGPT script parsing for fashion, dance, and adult Indian woman constraints."""
        raw_gpt_response = (
            "```json\n"
            "{\n"
            '  "title": "Chaleya - Chic Pastel Co-ord Dance Reel",\n'
            '  "hook": "Watch till the drop! ✨",\n'
            '  "scene_breakdown": [\n'
            '    {"seconds": "0-3s", "visual": "Adult Indian woman (age 22) smiles and starts rhythm footwork in pastel co-ord set", "narration": ""},\n'
            '    {"seconds": "4-7s", "visual": "Full body energetic spin showing sneakers and fluid outfit movement", "narration": ""},\n'
            '    {"seconds": "8-10s", "visual": "Signature hook step finish with confident gaze to camera", "narration": ""}\n'
            '  ],\n'
            '  "song_name": "Chaleya",\n'
            '  "artist": "Arijit Singh, Shilpa Rao",\n'
            '  "clothing_details": "Pastel lavender oversized blazer matching cropped shorts and white chunky sneakers",\n'
            '  "choreography": "Smooth lyrical Bollywood arm gestures and subtle hip rhythm",\n'
            '  "camera_lighting": "Soft natural window lighting, 9:16 vertical full body portrait, smooth slow zoom-in",\n'
            '  "video_generation_prompt": "Ultra-realistic 9:16 vertical 10-second cinematic video of a fictional 22-year-old Indian woman with natural hair and realistic anatomy dancing fluidly to a modern rhythm.",\n'
            '  "licensing_notes": "Use official Instagram audio library tag for Chaleya.",\n'
            '  "call_to_action": "Rate this outfit 1-10 in the comments below! 👇"\n'
            "}\n"
            "```"
        )
        bm = BrowserManager(self.config)
        client = ChatGPTClient(bm, self.config.chatgpt_conversation_url)
        script = client._parse_script_json(raw_gpt_response)

        self.assertIsNotNone(script)
        self.assertEqual(script.song_name, "Chaleya")
        self.assertEqual(script.artist, "Arijit Singh, Shilpa Rao")
        self.assertIn("Pastel lavender", script.clothing_details)
        self.assertIn("Ultra-realistic", script.video_generation_prompt)
        self.assertTrue(bool(script.scenes or script.choreography))

    def test_4_caption_generator_output(self):
        """Validates caption generation with fashion hashtags and audio credit."""
        cap_gen = CaptionGenerator()
        meta = cap_gen.generate(
            topic_title="Chaleya (Arijit Singh)",
            category="Indian Fashion & Dance",
            hook="Obsessed with this beat! ✨",
            narration="Trending dance routine featuring modern pastel co-ord casual fashion.",
            duration_sec=10.0,
            song_name="Chaleya",
            artist="Arijit Singh, Shilpa Rao"
        )

        self.assertIn("🎵 Audio: Chaleya by Arijit Singh, Shilpa Rao", meta.caption)
        self.assertIn("Obsessed with this beat!", meta.caption)
        self.assertTrue(any("Indian" in t or "Dance" in t or "Bollywood" in t for t in meta.hashtags), f"Expected tags, got: {meta.hashtags}")

    def test_5_settings_categories_updated(self):
        """Verifies settings.json topic categories reflect Indian fashion & dance."""
        cats = self.config.topic_categories
        self.assertTrue(any("Indian" in c or "Dance" in c or "Fashion" in c for c in cats), f"Categories not updated: {cats}")

if __name__ == "__main__":
    unittest.main()
