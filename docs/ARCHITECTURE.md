# Architecture — Prayonit Marketing Engine v1.0

## File structure

```
prayonit_social_automation/
  campaigns/          50 campaign JSON files (pain point, hooks, angles, hashtags, weight)
  formulas/           15 advertising-formula JSON files
  personas/           15 audience persona JSON files
  seasonality/        holiday/season JSON files with date rules
  data/               data/prayonit_marketing.db (SQLite), buffer_metrics_schema.json
  logs/               reserved for future file-based logging
  output/             locally rendered feed/Story preview images
  tests/              pytest suite, fully mocked (no live network calls)
  scripts/            generate_marketing_brain.py (offline content generator)
  supabase/
    migrations/       SQL for social_tracking_links / social_tracking_clicks
    functions/track-download/   Layer 2 Edge Function source (not deployed automatically)
  prayonit_social.py  CLI entry point (thin orchestrator)
  campaign_engine.py  campaign/formula/persona/seasonality selection + non-repetition
  prompt_builder.py   Gemini prompt construction + platform caption/hashtag rules
  image_renderer.py   feed (1080x1350) and Story (1080x1920) image rendering
  buffer_client.py    Buffer GraphQL client (post creation, schema introspection, metrics)
  history_store.py    SQLite persistence layer (sqlite3 only, no ORM)
  tracking.py         tracked-link generation (Layer 1)
  analytics.py        analytics / discover-buffer-metrics CLI logic
  config.py           centralized environment/config loading
```

## Data flow (one `run`)

1. `config.py` loads `.env` and validates required variables for the current
   `TEST_MODE`.
2. `campaign_engine.choose_selection()` picks a campaign, formula, persona,
   and active seasonal context, honoring weights and non-repetition rules.
3. `tracking.create_tracked_link()` mints one tracked URL per feed platform
   (Facebook, Instagram, Threads) and stores the mapping in SQLite.
4. `prompt_builder.generate_ad_copy()` builds a structured Gemini prompt
   (campaign + formula + persona + season + slot + tracked URL) and parses
   the strict JSON response.
5. `image_renderer.compose_ad()` / `compose_story_ad()` render the feed and
   Story images from the same background.
6. In production mode, images are uploaded to Supabase
   (`generated/feed/`, `generated/story/`), and `buffer_client.buffer_create_post()`
   schedules five Buffer items (Facebook post/Story, Instagram post/Story,
   Threads post), each wrapped in its own try/except.
7. `history_store.py` records the run, and each published/failed post, in
   `data/prayonit_marketing.db`.

## Safety model

- `TEST_MODE=true` (the default) stops after generating local preview images.
  No uploads, no Buffer calls, no post is ever marked `scheduled`.
- Every Buffer item failure is isolated; the run continues and prints a
  final success/failure summary.
- `get_performance_multiplier()` in `campaign_engine.py` is a documented
  placeholder that always returns `1.0` today — the single integration point
  for future analytics-driven weighting.
