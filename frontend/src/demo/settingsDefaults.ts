// Generated from backend/api/routes/settings.py DEFAULTS, with demo-friendly
// overrides (generic categories, @yourbrand handle). Data only.
export const SETTINGS_DEFAULTS: Record<string, Record<string, unknown>> = {
  "approval": {
    "instagram_auto_enabled": false,
    "instagram_auto_minutes": 60,
    "tiktok_auto_enabled": false,
    "tiktok_auto_minutes": 60,
    "youtube_auto_enabled": true,
    "youtube_auto_minutes": 60,
    "require_manual_for_categories": []
  },
  "schedule": {
    "daily_slots": [
      "08:00",
      "11:00",
      "14:00",
      "18:00",
      "21:00"
    ],
    "timezone": "UTC",
    "max_per_day": 5,
    "optimize_times": true
  },
  "ai": {
    "classifier_model": "groq/openai/gpt-oss-120b",
    "caption_model": "groq/openai/gpt-oss-120b",
    "refine_model": "google/gemma-4-31b-it:free"
  },
  "telegram": {
    "mode": "poll",
    "chat_id": "",
    "preview_push_enabled": true,
    "always_preview": true,
    "rich_publish_notify": true,
    "admin_controls": true
  },
  "music": {
    "preferred_source": "licensed",
    "pixabay_query": "cinematic upbeat",
    "swap_on_detect_original": false,
    "mood_match": true,
    "favourite_boost": 3.0,
    "usage_weight": 0.3,
    "cooldown_recent_cap": 10
  },
  "caption": {
    "use_feedback": true,
    "use_trends": true,
    "self_critique": true,
    "draft_with_groq": false,
    "use_hook_library": true,
    "hook_templates": [],
    "cta_style": "send"
  },
  "hashtags": {
    "ab_test": true,
    "blocked": [],
    "curated_enabled": true,
    "blend_count": 3,
    "pools": {
      "instagram": [],
      "tiktok": [],
      "youtube": []
    }
  },
  "monetize": {
    "enabled": false,
    "cta_text": "",
    "youtube_link": "",
    "platforms": [
      "instagram",
      "tiktok",
      "youtube"
    ]
  },
  "vision": {
    "enabled": true,
    "provider": "auto",
    "nightly_limit": 50
  },
  "selection": {
    "use_performance": true,
    "performance_weight": 0.5,
    "min_duration_s": 10.0,
    "min_short_side": 720,
    "min_hook_score": 0.0,
    "require_video_only": true,
    "quality_probe_enabled": true,
    "min_quality_score": 0.0,
    "require_classified": true,
    "category_cooldown_categories": 20
  },
  "taxonomy": {
    "categories": [
      "food",
      "fitness",
      "nature",
      "culture",
      "tech",
      "beach",
      "lifestyle",
      "travel"
    ]
  },
  "uploads": {
    "max_mb": 500,
    "allowed_types": [
      ".mp4",
      ".mov",
      ".m4v",
      ".webm"
    ],
    "auto_probe": true,
    "url_fetch": true
  },
  "platforms": {
    "instagram_enabled": true,
    "youtube_enabled": true,
    "tiktok_enabled": true,
    "instagram": {
      "hashtag_suffix": [
        "yourbrand",
        "reels",
        "creators"
      ]
    },
    "tiktok": {
      "hashtag_suffix": [
        "fyp",
        "yourbrand",
        "creators"
      ]
    },
    "youtube": {
      "hashtag_suffix": [
        "Shorts",
        "YourBrand"
      ],
      "playlists_enabled": true
    }
  },
  "youtube_playlists": {},
  "analytics": {
    "ingest_interval_hours": 6
  },
  "video": {
    "auto_stabilize": true,
    "remove_watermarks": false,
    "watermark_position": "bottom",
    "enhance_quality": true,
    "denoise": true,
    "denoise_strength": "light",
    "sharpen": true,
    "sharpen_amount": 0.4,
    "crf": 20,
    "preset": "medium",
    "smooth_motion": false,
    "smooth_fps": 60
  },
  "decaption": {
    "enabled": false,
    "algorithm": "hybrid",
    "detect_mode": "auto",
    "custom_bbox": "",
    "min_confidence": 0.35,
    "dilate_px": 6,
    "fallback": "blur"
  },
  "color": {
    "lut_mode": "category",
    "fixed_lut": "",
    "use_vision": false,
    "intensity": 1.0
  },
  "pipeline": {
    "env_mode": "dev",
    "auto_publish_enabled": true,
    "auto_create_enabled": true,
    "auto_create_mode": "approval",
    "auto_create_strategy": "diverse",
    "auto_create_category": "",
    "auto_create_reel_type": "merge",
    "stages_enabled": {
      "index": true,
      "classify": true,
      "resize": true,
      "edit": true,
      "caption": true,
      "upload": true
    }
  },
  "storage": {
    "reels_max_gb": 5,
    "reels_min_age_days": 7
  },
  "intro": {
    "enabled": true,
    "mode": "generated",
    "asset_file": "",
    "duration_s": 1.5,
    "animation": "fade",
    "bg_color": "#000000",
    "bg_opacity": 0.15,
    "text_padding_h": 40,
    "header_enabled": true,
    "header_text": "",
    "header_color": "#ffffff",
    "header_font": "",
    "header_font_size": 52,
    "header_order": 0,
    "header_bottom_padding": 0,
    "subheader_enabled": true,
    "subheader_text": "",
    "subheader_color": "#cccccc",
    "subheader_font": "",
    "subheader_font_size": 36,
    "subheader_order": 1,
    "subheader_bottom_padding": 16,
    "show_tags": true,
    "tags_color": "#ffffff",
    "tags_font": "",
    "tags_font_size": 40,
    "tags_order": 2,
    "tags_bottom_padding": 0,
    "show_category": true,
    "category_color": "#aaaaaa",
    "category_font": "",
    "category_font_size": 30,
    "category_order": 3,
    "category_bottom_padding": 0,
    "show_handle": true,
    "handle_color": "#ffffff",
    "handle_font": "",
    "handle_font_size": 28,
    "handle_order": 5,
    "handle_bottom_padding": 0,
    "show_hook": false,
    "hook_source": "caption_line1",
    "hook_text": "",
    "hook_color": "#ffffff",
    "hook_font": "",
    "hook_font_size": 56,
    "hook_order": -1,
    "hook_bottom_padding": 24
  },
  "cast": {
    "enabled": false,
    "mode": "generated",
    "asset_file": "",
    "duration_s": 1.5,
    "animation": "fade",
    "bg_color": "#000000",
    "bg_opacity": 0.15,
    "text_padding_h": 40,
    "cta_enabled": true,
    "cta_text": "Send this to a friend who needs it",
    "cta_color": "#ffffff",
    "cta_font": "",
    "cta_font_size": 52,
    "cta_order": 0,
    "cta_bottom_padding": 0,
    "subheader_enabled": true,
    "subheader_text": "",
    "subheader_color": "#cccccc",
    "subheader_font": "",
    "subheader_font_size": 36,
    "subheader_order": 1,
    "subheader_bottom_padding": 16,
    "show_tags": true,
    "tags_color": "#ffffff",
    "tags_font": "",
    "tags_font_size": 40,
    "tags_order": 2,
    "tags_bottom_padding": 0,
    "show_episode": true,
    "episode_color": "#aaaaaa",
    "episode_font": "",
    "episode_font_size": 30,
    "episode_order": 4,
    "episode_bottom_padding": 0,
    "show_handle": true,
    "handle_color": "#ffffff",
    "handle_font": "",
    "handle_font_size": 28,
    "handle_order": 5,
    "handle_bottom_padding": 0,
    "minimal_cta": false
  },
  "branding": {
    "overlay_enabled": true,
    "ig_handle": "@yourbrand",
    "custom_text": "",
    "font": "",
    "font_size": 0,
    "bar_height": 45,
    "show_on_thumbnail": true,
    "bar_bg_color": "#ffffff",
    "text_color": "#000000",
    "bar_opacity": 1.0,
    "bar_position": "bottom",
    "location_side": "left",
    "handle_side": "right"
  },
  "merge": {
    "enabled": true,
    "auto_run": false,
    "clips_per_reel": 4,
    "target_duration_s": 30.0,
    "selection_strategy": "diverse",
    "scene_aware": true,
    "transition": "fade",
    "transition_ms": 500,
    "beat_sync": true,
    "min_clip_score": 0.0,
    "cut_min_s": 1.5,
    "cut_max_s": 3.0,
    "min_segments": 20,
    "min_main_videos": 10,
    "segments_per_clip": 3,
    "split_stock_local": true,
    "min_stock_segments": 8,
    "min_local_segments": 12,
    "auto_fetch_stock": false,
    "auto_fetch_pexels": 3,
    "auto_fetch_pixabay": 3,
    "cleanup_segments": true,
    "grade": "",
    "grain": false,
    "vignette": false,
    "auto_count": true,
    "audio_mode": "music",
    "music_fade_s": 1.0,
    "slow_motion": true,
    "slow_motion_factor": 0.85,
    "ken_burns": true,
    "transition_variety": true,
    "loop_friendly": false,
    "adaptive_fx": true,
    "smart_select": true,
    "select_sharpness_weight": 0.5,
    "select_min_sharpness": 0.0,
    "color_match": true,
    "deband": true,
    "hard_cuts_on_beat": true,
    "smooth_slowmo": false,
    "smooth_slowmo_max_s": 3.0,
    "deblock": true,
    "sharpen": false,
    "sharpen_amount": 0.3,
    "strong_denoise": false,
    "dedupe_enabled": true,
    "subshot_cooldown_reels": 3,
    "dedupe_soft_weight": 0.5,
    "proven_topup": true,
    "proven_min_score": 0.5,
    "dynamic_count": true,
    "max_cuts_per_source": 1
  },
  "stock": {
    "enabled": true,
    "source": "pexels",
    "per_category_query": {},
    "max_clips_per_search": 5,
    "min_short_side": 720,
    "min_duration_s": 5.0
  },
  "voiceover": {
    "enabled": false,
    "voice": "en-US-AriaNeural",
    "rate": "+0%",
    "narration_source": "caption_hook",
    "subtitles_enabled": true,
    "subtitle_position": "bottom",
    "subtitle_font_size": 28,
    "subtitle_color": "#ffffff",
    "music_duck_volume": 0.08
  },
  "editor": {
    "enabled": true,
    "proxy_height": 480,
    "proxy_ttl_days": 7,
    "autosave_seconds": 15,
    "keep_versions": 20,
    "max_text_layers": 20,
    "max_image_layers": 10,
    "max_cuts": 40,
    "export_mode": "overwrite",
    "preview_lut": true
  }
};
