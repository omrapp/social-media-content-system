"""Viral hook-template library for captions — injected into caption prompt."""

import logging
import random

log = logging.getLogger(__name__)

# Structure: category → arc_position → list of hook patterns.
# Arc positions: "opener", "build", "climax", "closer"
# "_DEFAULT" key covers any category not explicitly listed.
_HOOK_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "_DEFAULT": {
        "opener": [
            "This in 60 seconds — save it before you need it 📌",
            "Nobody talks about this side of it.",
            "Save this before it gets crowded —",
            "The part that never makes the guides:",
            "What to know before you go —",
            "This will ruin every other alternative for you.",
            "Warning: this has a long waitlist for a reason.",
        ],
        "build": [
            "Here's what surprised me most:",
            "The one thing they don't tell you:",
            "And then it got even better —",
            "This is where it stopped being a trip and started being a story.",
            "Nobody mentioned this part in any travel blog.",
        ],
        "climax": [
            "This was the moment.",
            "I can't stop thinking about this place.",
            "Worth every second.",
            "Nothing prepared me for this.",
            "This is the shot that made the whole trip worth it.",
        ],
        "closer": [
            "See you in the next destination 🌍",
            "Which country should I explore next?",
            "Follow for the next one 👇",
            "That's a wrap on this chapter. Next one's going to be even better.",
            "More countries incoming — follow so you don't miss episode 1.",
        ],
    },
    "hidden_gem": {
        "opener": [
            "This place has zero tourists (for now) —",
            "The hidden gem everyone will know in 5 years:",
            "The hidden side of it: what Google won't show you —",
            "Off every map, on every bucket list:",
            "Locals asked me not to post this. Posting it anyway.",
        ],
        "build": [
            "The more I explored, the more I understood why this stays secret.",
            "No crowds. No queues. Just this:",
            "Here's what you miss when you stick to the tourist trail:",
        ],
        "climax": [
            "Peak hidden gem energy.",
            "This is why you leave the guidebook at home.",
            "I had the whole place to myself.",
        ],
        "closer": [
            "Save it before it blows up. 🤫",
            "DM me if you want the exact coordinates.",
            "Who else knows about this? 👇",
        ],
    },
    "budget": {
        "opener": [
            "Real cost of this in 2026 (actual receipts):",
            "Budget travel tip nobody tells you:",
            "Proof you don't need money to travel well —",
            "This cost less than a restaurant meal back home.",
            "Full day. Incredible experience. Under $20.",
        ],
        "build": [
            "The cheap option that beats the expensive one every time:",
            "Here's where the locals actually eat:",
            "Skip the tourist markup with this one trick:",
        ],
        "climax": [
            "Best value moment of the entire trip.",
            "This is what budget travel actually looks like.",
            "Proof that experiences beat price tags.",
        ],
        "closer": [
            "Full budget breakdown in the next episode 👇",
            "Follow for more budget-proof destinations.",
            "Save this for when you think travel is too expensive.",
        ],
    },
    "culture": {
        "opener": [
            "The moment I understood this culture:",
            "History you can actually touch:",
            "Nobody warned me how deeply this would hit.",
            "This tradition is 1,000 years old and still going strong.",
            "One afternoon here taught me more than a year of school.",
        ],
        "build": [
            "The locals showed me something no tour guide covers:",
            "Once you know the history, you can't unsee it:",
            "This is what the postcards never show you:",
        ],
        "climax": [
            "A moment I'll carry for a long time.",
            "Some places change you a little. This one changed me a lot.",
            "This is why I travel.",
        ],
        "closer": [
            "Next episode: a tradition even fewer outsiders have seen.",
            "Follow to keep exploring with me 🌍",
            "What culture has moved you most? 👇",
        ],
    },
    "nature": {
        "opener": [
            "This exists on Earth and most people will never see it.",
            "Nature said: I'm not done impressing you.",
            "No filter. No edit. This is real.",
            "The trail nearly killed me. The view made it worth it.",
            "I've seen a lot of landscapes. This one stopped me cold.",
        ],
        "build": [
            "Two hours of hiking later:",
            "The last 10 minutes of the trail are the hardest — and the best:",
            "Then the clouds parted and I understood why people come here:",
        ],
        "climax": [
            "Nature won today.",
            "Some views you just have to stand in silence for.",
            "No photo does this justice — but I tried.",
        ],
        "closer": [
            "Next: a natural wonder even fewer people know about.",
            "Follow to see more landscapes like this 🏔",
            "Would you make this hike? 👇",
        ],
    },
    "food": {
        "opener": [
            "Best meal of my entire trip 🍽",
            "This changed my opinion of the local cuisine:",
            "I came for the views. I stayed for the food.",
            "Nobody told me about this dish. That ends now.",
            "Spent €8. Ate better than any Michelin star I've been to.",
        ],
        "build": [
            "Then the third dish arrived and I completely gave up trying to pace myself:",
            "The chef has been making this same recipe for 40 years:",
            "Here's what the locals order (that's never on the tourist menu):",
        ],
        "climax": [
            "New top 3 meal. Easily.",
            "I went back the next day. And the day after.",
            "This is the dish I'm still dreaming about.",
        ],
        "closer": [
            "Full food guide for this city in the next episode.",
            "Follow for more underrated food finds 🍜",
            "What's the best meal you've ever had abroad? 👇",
        ],
    },
    "beach": {
        "opener": [
            "The beach they forgot to put on Google Maps.",
            "I found the last empty beach around. Here's where:",
            "Not the Caribbean. Not the Maldives. Guess where.",
            "Water this colour should be illegal.",
            "Two hours from the airport. Zero tourists. This.",
        ],
        "build": [
            "The sand is the kind that doesn't stick to your feet.",
            "Then I swam out 50 metres and the colour changed completely:",
            "No beach bar. No sunbed rental. Just this:",
        ],
        "climax": [
            "Peak beach energy. Nothing else to say.",
            "The most peaceful two hours I've had in years.",
            "This is what the travel brochures are actually trying to show.",
        ],
        "closer": [
            "Exact location in my bio 📍",
            "Follow for more hidden beaches 🏖",
            "Would you fly here just for this? 👇",
        ],
    },
}


def hook_block(
    category: str | None,
    arc_position: str | None,
    trend_topic: str = "",
) -> str:
    """Return a prompt fragment with 2-3 viral hook templates to inspire the LLM.

    Args:
        category: Content category (e.g. "hidden_gem", "food"). None for generic hooks.
        arc_position: Story arc position ("opener", "build", "climax", "closer").
                      None falls back to "opener" hooks.
        trend_topic: Optional trending topic string to include as a weave-in hint.

    Returns:
        Prompt fragment string, or "" on any error (best-effort).
    """
    try:
        from backend.api.routes.settings import get_setting  # avoid circular at module level
        cfg = get_setting("caption") or {}
    except Exception as exc:
        log.warning("hook_library: could not read settings (%s), using defaults", exc)
        cfg = {}

    try:
        # Allow user-supplied templates to completely override code defaults.
        user_templates: list[str] = cfg.get("hook_templates") or []
        if user_templates:
            picks = random.sample(user_templates, min(3, len(user_templates)))
        else:
            arc = (arc_position or "opener").lower()
            norm_category = (category or "").lower().replace(" ", "_")

            # Try category-specific arc, fall back to _DEFAULT arc, fall back to _DEFAULT opener.
            category_hooks = _HOOK_TEMPLATES.get(norm_category, {})
            arc_hooks = (
                category_hooks.get(arc)
                or _HOOK_TEMPLATES["_DEFAULT"].get(arc)
                or _HOOK_TEMPLATES["_DEFAULT"]["opener"]
            )

            picks = random.sample(arc_hooks, min(3, len(arc_hooks)))

        lines = [
            "Viral hook inspiration (adapt freely, don't copy verbatim — pick the one that fits best):",
        ]
        for hook in picks:
            lines.append(f"• {hook}")

        if trend_topic:
            lines.append(
                f"(Optional trend angle to weave in naturally: {trend_topic})"
            )

        return "\n" + "\n".join(lines)

    except Exception as exc:
        log.warning("hook_library: hook_block failed (%s), skipping hook injection", exc)
        return ""
