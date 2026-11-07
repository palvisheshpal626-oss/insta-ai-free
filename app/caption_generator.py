import re
from typing import Dict, Any, List
from dataclasses import dataclass, asdict

@dataclass
class ReelMetadata:
    topic: str
    caption: str
    hashtags: List[str]
    formatted_post_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CaptionGenerator:
    """Generates Instagram caption, hashtags, and publication text grounded strictly in the verified topic and script."""

    # Categorized hashtags to avoid fabricated or irrelevant spam
    CATEGORY_TAGS = {
        "Indian Fashion & Dance": [
            "#IndianFashion", "#DanceReels", "#BollywoodSongs", "#TrendingReels",
            "#OutfitInspiration", "#IndianOutfits", "#ReelKaroFeelKaro", "#FashionReels"
        ],
        "Trending Bollywood & Indian Songs": [
            "#BollywoodMusic", "#TrendingAudio", "#SongReels", "#MusicReels",
            "#DanceTrend", "#DesiVibes", "#BollywoodSongs"
        ],
        "Indian Modern Fashion & Western Outfits": [
            "#OOTDIndia", "#WesternWearIndia", "#StreetStyleIndia", "#CasualChic",
            "#OutfitGoals", "#FashionInspoIndia", "#StyleInspiration"
        ],
        "Trending Dance Reels & Choreography": [
            "#ChoreographyReels", "#DanceCover", "#HookStep", "#DanceChallenge",
            "#IndianDancers", "#DanceTrend", "#DanceWithMe"
        ],
        "Contemporary Fusion & Co-Ord Sets": [
            "#FusionWear", "#CoOrdSet", "#ModernIndian", "#ChicOutfits", "#TrendyLooks"
        ],
        "Indian Street Style & Casuals": [
            "#IndianStreetStyle", "#DenimLook", "#CasualOutfits", "#SneakerHeadIndia"
        ],
        "Artificial Intelligence": ["#ArtificialIntelligence", "#AI", "#TechNews", "#FutureTech", "#MachineLearning", "#AINews"],
        "Technology": ["#Technology", "#TechTrends", "#Innovation", "#Gadgets", "#Future", "#TechUpdate"],
    }

    def generate(self, topic_title: str, category: str, hook: str, narration: str, duration_sec: float, song_name: str = "", artist: str = "") -> ReelMetadata:
        # Build clean, engaging caption
        clean_hook = hook.strip(' "\'')
        clean_narration = narration.strip(' "\'')

        caption_lines = [
            f"✨ {clean_hook}",
            "",
            f"💃 {clean_narration}"
        ]

        if song_name:
            credit = f"🎵 Audio: {song_name}" + (f" by {artist}" if artist else "")
            caption_lines.extend(["", credit])

        caption_lines.extend([
            "",
            "✨ Rate this look & dance vibe from 1-10 in the comments below! 👇"
        ])
        caption = "\n".join(caption_lines)

        # Select matching hashtags
        tags = set(self.CATEGORY_TAGS.get(category, self.CATEGORY_TAGS["Indian Fashion & Dance"]))
        tags.update(["#ReelsInstagram", "#InstaReels", "#ExplorePage"])

        # Format full post text
        tag_string = " ".join(list(tags)[:8])
        full_text = f"{caption}\n\n{tag_string}"

        return ReelMetadata(
            topic=topic_title,
            caption=caption,
            hashtags=list(tags)[:8],
            formatted_post_text=full_text
        )

