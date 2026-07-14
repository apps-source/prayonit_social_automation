# Creative Engine v2

This document describes the coordinated marketing-creative upgrade covering
ad-copy generation, Story/feed layout, platform-specific Buffer placement,
brand assets, theology-safe language, and CTA deduplication. It replaces the
previous single-headline/body/cta message structure end-to-end.

## 1. New message hierarchy

Every ad now follows a fixed emotional-to-action flow:

```
Pain or emotional need
  -> Spiritual action
  -> How Prayonit helps (app benefit)
  -> Download action
  -> 14-day free-trial support
```

Gemini returns strict JSON with these keys (`prompt_builder.REQUIRED_AD_COPY_KEYS`):

| Key | Purpose |
|---|---|
| `brand_header` | Small brand name, normally "PRAYONIT" |
| `pain_headline` | Names the pain/emotional need (max ~9 words) |
| `spiritual_action` | The approved spiritual action sentence (see below) |
| `app_benefit` | Must directly answer `pain_headline`; always references a guided/personalized prayer + the user's mood/feelings/situation |
| `download_cta` | Always forced to exactly `"DOWNLOAD PRAYONIT"` |
| `trial_support` | Must explicitly say "14-day free trial" |
| `facebook_caption` / `instagram_caption` / `threads_caption` | Full per-platform captions |
| `story_headline`, `story_spiritual_action`, `story_app_benefit`, `story_download_cta`, `story_trial_support` | Compact Story equivalents |

`prompt_builder.apply_brand_enforcement()` programmatically repairs any field
that fails validation instead of trusting Gemini's output as-is:

- `enforce_download_cta()` — forces `download_cta` / `story_download_cta` to `"DOWNLOAD PRAYONIT"` always.
- `enforce_trial_support()` — falls back to an approved 14-day trial phrase if the duration is missing or a forbidden phrase (e.g. "try it free today") is used.
- `enforce_app_benefit_matches_pain()` / `app_benefit_matches_pain()` — rejects a generic benefit that doesn't mention a guided/personalized prayer connected to the user's mood, feelings, worries, gratitude, or situation, replacing it with the approved fallback: *"Get a guided, personalized prayer based on how you feel right now."*
- `enforce_theology_safety()` — removes any sentence containing a forbidden theological claim (see below) from `spiritual_action` / `app_benefit` / their Story equivalents, falling back to an approved sentence if the field would otherwise be empty.

## 2. Theology-safe language

Approved concepts (the user prays to God):

- Give your worries to God in prayer.
- Lay today's burdens before the Lord.
- Bring what is on your heart to God.
- Seek God's guidance through prayer.
- Thank God for His blessings. / Give God praise.
- Find peace through prayer.
- End your day by giving your burdens to God.

Forbidden (checked by `prompt_builder.FORBIDDEN_THEOLOGY_PHRASES`):

- God is praying to the user / speaking through the app.
- Prayonit speaks on God's behalf.
- The AI knows God's will.
- Guaranteed healing, sleep, peace, or relief.
- "Let God meet you with a personalized prayer," "Receive God's message," "Hear what God wants to tell you," etc.

"Personalized Scripture" remains allowed language (unchanged from Brand Brain).

## 3. Modular theology component library

`brand/theology_actions.json` holds approved, reusable spiritual-action
sentence pools (not 200 fixed ads):

`surrender_actions`, `guidance_actions`, `gratitude_actions`, `praise_actions`,
`comfort_actions`, `morning_actions`, `evening_actions`, `anxiety_actions`,
`grief_actions`, `purpose_actions`, `relationship_actions`,
`financial_stress_actions`.

`config.load_theology_actions()` loads the file fresh each call.
`campaign_engine.pick_spiritual_action(campaign, slot)`:

1. Maps the campaign's name/pain_point/goal to a pool via keyword matching (e.g. "anxi" -> `anxiety_actions`, "grief"/"griev" -> `grief_actions`), falling back to `morning_actions`/`evening_actions` by slot, and finally `surrender_actions`.
2. Avoids sentences used in the last 10 selections (tracked in `data/recent_theology_components.json`, a small local JSON file — **not** part of the SQLite history database, so no schema/migration changes were needed) when an untried alternative exists in the pool.
3. Returns the chosen sentence, which is injected into the Gemini prompt as the required spiritual-action anchor. Gemini may adapt grammar only; it must not invent a new theological claim.

### Adding a new approved spiritual action

Edit `brand/theology_actions.json` and add a short, theologically appropriate
sentence to the relevant pool (or a new pool key, then add a matching keyword
to `campaign_engine._CAMPAIGN_KEYWORD_POOLS` if it should be auto-selected for
certain campaigns). No code change is required for existing pools.

## 4. Story layout (1080x1920)

`image_renderer.compose_story_ad()` hierarchy, top to bottom:

A. Small logo (or `brand_header` text fallback) near the top.
B. Brand name beneath the logo.
C. `story_headline` in the upper-middle safe zone.
D. `story_spiritual_action` beneath it.
E. `story_app_benefit` beneath that (wrapped to ~3 lines).
F. Large `DOWNLOAD PRAYONIT` button (larger than the previous CTA button).
G. `story_trial_support` immediately below the button.
H. App Store / Google Play badges (or text fallback) beneath the trial text.

A `bottom_safe_zone_y = height - 220` boundary keeps all essential content
(including badges) above where Instagram/Facebook Story reply controls
render. The old tiny bottom "Download Prayonit" footer line has been removed.
Spacing between elements is computed dynamically from each element's
rendered text height, so longer/shorter copy does not overlap.

## 5. Feed layout (1080x1350)

`image_renderer.compose_ad()` hierarchy: small brand/logo -> `pain_headline`
-> `spiritual_action` -> `app_benefit` (on a softer, lower-opacity translucent
panel than before) -> large `DOWNLOAD PRAYONIT` button -> `trial_support`
text. The button is now visually larger, and the panel behind `app_benefit`
uses `fill=(0, 0, 0, 90)` instead of the previous heavier `110`/solid-looking
box.

## 6. Brand assets

New config paths (`config.py`), all with safe, always-defined defaults:

```python
BRAND_ASSETS_DIR = PROJECT_ROOT / "assets" / "branding"
LOGO_PATH = BRAND_ASSETS_DIR / "prayonit_logo.png"
APP_STORE_BADGE_PATH = BRAND_ASSETS_DIR / "app_store_badge.png"
GOOGLE_PLAY_BADGE_PATH = BRAND_ASSETS_DIR / "google_play_badge.png"
```

**Asset requirements (you must supply these files manually):**

- PNG format
- Transparent background
- High resolution (at least 2x the rendered display size to stay sharp)
- Official Apple/Google badge artwork only — never generate fake badges
- Visually matched badge heights (both badges are rendered at the same
  `target_height` so mismatched source aspect ratios still look balanced)

**Fallback behavior** (`image_renderer.load_brand_asset()`): if a file is
missing or fails to load, rendering never crashes — it logs a
`UserWarning` and falls back to text:

- Logo fallback: the `brand_header` text (normally "PRAYONIT")
- Store badge fallback: "Available on the App Store and Google Play"

## 7. Platform-specific Buffer placement

Preserved/verified in `buffer_client.buffer_create_post()`:

- **Facebook feed**: full caption, clickable URL stays in the caption text. `metadata.facebook = {"type": post_type}` (unchanged).
- **Instagram feed**: no raw URL in the caption (`build_platform_captions()` never appends one); the destination URL is placed in `metadata.instagram.link` (set from the `link` argument, which callers pass as the tracked/destination URL from `tracking.create_tracked_link()`). Hashtags are preserved. The trial phrase appears exactly once (Gemini's caption body has all trial-wording sentences stripped via `_strip_duplicate_trial_cta_sentences()`, then the exact phrase "Start your 14-day free trial." is appended once).
- **Instagram Story**: unchanged — no `link` field is added (Buffer's `InstagramStoryMetadataInput` support for a link field has not been verified), `shouldShareToFeed=False`, `type="story"` preserved exactly as before.
- **Threads**: URL remains in the caption; `metadata.threads.locationName` / `locationId` are included only when `config.THREADS_LOCATION_NAME` / `THREADS_LOCATION_ID` are non-empty; copy stays conversational; at most one trial-wording sentence is kept (`_keep_only_first_trial_cta_sentence()` — Threads has no programmatic trial line, so a single Gemini-written mention is fine, but duplicates are removed).

## 8. CTA deduplication

- `prompt_builder._strip_duplicate_trial_cta_sentences()` (Instagram): removes **every** sentence matching 14-day-trial wording from Gemini's caption body, since the required phrase is always appended programmatically afterward.
- `prompt_builder._keep_only_first_trial_cta_sentence()` (Facebook/Threads): keeps the **first** trial-wording sentence and removes any additional duplicates, since these captions have no programmatic trial line appended.
- Both use `_DUPLICATE_TRIAL_CTA_PATTERN`, matching `start|begin|try ... 14-day ... trial` case-insensitively, covering wording variations like "Get Prayonit today and start your 14-day free trial," "Begin your 14-day free trial today," and "Try Prayonit with a 14-day free trial."

## 9. Validation and enforcement summary

`prompt_builder.apply_brand_enforcement()` runs (in order): legacy CTA/story_cta
enforcement (backward compatible, only if those legacy keys are present),
forbidden-phrase and feature-claim removal on all caption-like fields,
trial-duration enforcement, then the Creative Engine v2 checks: theology
safety on `spiritual_action`/`app_benefit` (and Story equivalents),
benefit-matches-pain repair, `download_cta`/`story_download_cta` forced to
`"DOWNLOAD PRAYONIT"`, and `trial_support`/`story_trial_support` forced to
include the 14-day duration. If Gemini's JSON is missing a required key
entirely, `generate_ad_copy()` still raises `RuntimeError` (fail-fast on
structurally invalid responses); enforcement/repair applies to
present-but-invalid field values.

## 10. What still needs to be supplied manually

This implementation does **not** include actual artwork. To get real logos
and badges rendering (instead of the text fallback), place these files in
the workspace:

```
assets/branding/prayonit_logo.png
assets/branding/app_store_badge.png
assets/branding/google_play_badge.png
```

Until then, rendering automatically uses the text fallback described in
Section 6 — no code changes needed once the files are added.

## Related docs

- `docs/BRAND_BRAIN.md` — underlying brand rules this builds on.
- `docs/CAMPAIGN_BRAIN.md` — campaign/persona/formula selection this is unchanged by.
- `docs/TRACKING.md` — tracked-URL generation used for `metadata.instagram.link` and caption URLs.
