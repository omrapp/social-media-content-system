"""
Caption-mood classifier for mood-matched background music (Enhancement G).

A tiny, $0, offline lexicon classifier: scan whatever text a clip already has
(the original IG caption + classification tags) and pick the dominant mood. The
mood then biases music selection — both the local-pack score and the Jamendo
fuzzytags fallback — so an adventurous clip gets energetic music and a serene
one gets ambient, instead of every clip getting the same generic bed.

Deliberately NOT an LLM call: this runs in the edit stage before the caption is
even generated, must be cheap/deterministic, and degrades to None (→ existing
category-based behaviour) whenever there's no usable text or no keyword hit.
"""

# Mood → music search/score keywords (Jamendo-friendly mood/genre words).
MOOD_TAGS = {
    "adventurous": "energetic upbeat adventure driving",
    "calm":        "ambient calm relaxing chill",
    "romantic":    "romantic emotional dreamy",
    "fun":         "happy playful upbeat groovy",
    "epic":        "cinematic epic dramatic",
    "reflective":  "ambient emotional contemplative",
}

# Keyword → mood. Substring match (so emoji + word stems both hit). Order of
# moods here is the tie-break preference when two moods score equal.
_MOOD_LEXICON = {
    "adventurous": ["adventure", "explore", "hike", "trek", "wild", "thrill",
                    "dive", "climb", "road trip", "off the beaten", "journey",
                    "conquer", "wander", "trail", "🧗", "🏔", "🚀"],
    "epic":        ["breathtaking", "stunning", "majestic", "grand", "epic",
                    "jaw-dropping", "unreal", "wonder", "mountain", "canyon",
                    "waterfall", "view", "skyline", "🤯", "😱"],
    "romantic":    ["romantic", "sunset", "love", "couple", "honeymoon",
                    "dreamy", "candle", "magical", "❤", "😍", "🌅"],
    "fun":         ["fun", "party", "vibrant", "colorful", "colourful",
                    "foodie", "delicious", "tasty", "street food", "market",
                    "dance", "festival", "😂", "🤩", "🥳", "🌮"],
    "calm":        ["serene", "peaceful", "quiet", "calm", "relax", "tranquil",
                    "still", "slow", "escape", "retreat", "zen", "hidden gem",
                    "🌿", "🧘", "😌"],
    "reflective":  ["culture", "history", "ancient", "temple", "tradition",
                    "heritage", "story", "memories", "reflect", "soul", "ruins",
                    "🛕", "📜"],
}


def mood_from_text(*parts: str | None) -> str | None:
    """Pick the dominant mood from one or more text fragments (caption, tags…).

    Returns a mood key from MOOD_TAGS, or None when no keyword matches — callers
    then keep the category-default music behaviour. Counts keyword occurrences per
    mood; ties broken by the lexicon's declared order."""
    text = " ".join(p for p in parts if p).lower()
    if not text:
        return None
    best_mood = None
    best_hits = 0
    for mood, words in _MOOD_LEXICON.items():
        hits = sum(text.count(w) for w in words)
        if hits > best_hits:
            best_hits = hits
            best_mood = mood
    return best_mood
