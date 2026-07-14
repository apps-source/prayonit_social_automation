# Brand Brain

`brand/brand_rules.json` is the single source of truth for Prayonit's brand
voice, approved calls-to-action, approved language, forbidden claims/
phrases, and the actual list of existing features. Every Gemini prompt
built by `prompt_builder.build_prompt()` includes a mandatory preamble
generated from this file, and every Gemini response is post-processed
against it before it's used anywhere (captions, Buffer posts, history).

This system does not change any scheduling, Buffer, Supabase, tracking, or
image-generation logic — it only shapes and enforces the marketing copy
itself.

## How it's loaded

`config.load_brand_rules()` reads and parses `brand/brand_rules.json` fresh
from disk. `config.BRAND_RULES` is a convenience copy loaded once at import
time. On import, the terminal prints:

```
Brand Brain loaded successfully.
Preferred CTA:
Start your 14-day free trial.
```

## How enforcement works (`prompt_builder.py`)

1. **Prompt injection** — `build_brand_brain_preamble()` renders the rules
   (features, approved CTAs, tone, forbidden claims/phrases) into a
   preamble that is prepended to every prompt sent to Gemini.
2. **CTA enforcement** — `enforce_cta()` replaces any CTA Gemini returns
   that isn't an exact match in `approved_ctas` with `preferred_cta`.
3. **Forbidden phrase enforcement** — `enforce_forbidden_phrases()` replaces
   any `never_say` phrase (e.g. "free app", "100% free") with the
   `preferred_cta`.
4. **Feature-claim enforcement** — `enforce_feature_claims()` removes any
   sentence referencing a small denylist of commonly-hallucinated features
   (e.g. "community forum", "live pastor") that are not in `core_features`.
   Anything that IS in `core_features` is never removed.
5. **URL enforcement** (from a prior change, still in effect) — Gemini is
   told never to include a URL, any URL it includes anyway is stripped, and
   the real destination/tracked URL is appended programmatically per
   platform.

All of this happens inside `generate_ad_copy()` via
`apply_brand_enforcement()`, so callers always receive already-enforced
copy.

## Editing the brand

Edit `brand/brand_rules.json` directly — no code changes needed for most
changes:

### Change CTAs
- Add/remove entries in `approved_ctas`.
- Change `preferred_cta` to whichever approved CTA should be used by
  default. It must also appear in `approved_ctas`.

### Change trial wording
- Update `trial_policy.length`, `trial_policy.preferred_phrase`, and
  `trial_policy.alternate_phrase`.
- If the preferred trial phrase changes, also update `preferred_cta` (and
  make sure it's present in `approved_ctas`) so enforcement stays
  consistent.

### Add future features
- Add the new feature to `core_features` — enforcement will then allow
  Gemini to reference it and will stop treating any matching denylist
  phrase in `prompt_builder.KNOWN_NONEXISTENT_FEATURE_PHRASES` as
  forbidden.
- If Gemini starts hallucinating a new kind of nonexistent feature not yet
  covered, add that phrase to
  `prompt_builder.KNOWN_NONEXISTENT_FEATURE_PHRASES` in code.

### Change tone or forbidden claims
- Edit `voice.tone`, `voice.avoid`, `approved_language`, `never_claim`, or
  `never_say`. These feed directly into the prompt preamble; `never_say`
  additionally drives automatic phrase replacement after generation.

### App store / website links
- `app_store_links` in this file are informational/reference values only.
  The actual URLs used in captions still come from `.env`
  (`IOS_DESTINATION_URL`, `ANDROID_DESTINATION_URL`,
  `DEFAULT_DESTINATION_URL`, `TRACKING_BASE_URL`) — update `.env`
  separately if those change.

## Testing

```bash
python -m pytest tests/test_brand_brain.py tests/test_prompt_builder.py -q
```
