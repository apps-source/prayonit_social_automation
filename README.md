# Prayonit Marketing Engine v1.0# Prayonit Social Automation — First Test



A modular, safety-first social media marketing automation system for## Where this goes

Prayonit. It picks a campaign/formula/persona/background (with holiday

awareness and non-repetition), generates ad copy with Gemini, rendersPut this folder anywhere on your Mac. The easiest location is:

feed + Story images, builds tracked links, and (only when `TEST_MODE=false`)

schedules posts to Buffer and records history/metrics locally.`~/Documents/prayonit-social-automation`



**`TEST_MODE=true` is the default and must stay `true` during development.**This first run happens locally. It will:

No live Buffer/Supabase calls happen while it is `true`.

1. Pick a random image from your existing public Supabase bucket.

## Architecture2. Ask Gemini for download-focused Prayonit ad copy.

3. Overlay the text using Python.

See `docs/ARCHITECTURE.md` for the full data-flow diagram. Short version:4. Save the finished image in the `output` folder.

5. Stop without posting while `TEST_MODE=true`.

```

config.py            central env/config loaderAfter the preview looks right, set `TEST_MODE=false`. It will then upload the

image_renderer.py     feed + Story image composition (PIL)finished image into `generated/` inside the same bucket and queue it through

history_store.py      SQLite: campaigns_used, published_posts,Buffer.

                       post_metrics, tracking_links, tracking_clicks

tracking.py           tracked-link generation (Layer 1)## Mac setup

buffer_client.py       Buffer GraphQL calls (post + metrics introspection)

analytics.py           metrics discovery / reporting commandsOpen Terminal and run:

campaign_engine.py     campaign/formula/persona/season selection

prompt_builder.py       Gemini prompt construction + platform captions```bash

prayonit_social.py      thin CLI entry point orchestrating all of the abovecd ~/Documents/prayonit-social-automation

scripts/generate_marketing_brain.py   offline generator for campaigns/formulas/personas/seasonality JSONpython3 -m venv .venv

campaigns/ formulas/ personas/ seasonality/   JSON "marketing brain" datasource .venv/bin/activate

tests/                 pytest suite (fully mocked, no live network calls)pip install -r requirements.txt

docs/                  architecture, tracking, analytics, campaign brain docscp .env.example .env

supabase/              SQL migration + Edge Function source for Layer 2 trackingopen -e .env

``````



## SetupFill in the missing keys, save the file, then run:



```bash```bash

cd ~/Documents/prayonit_social_automationpython prayonit_social.py --slot morning

python3 -m venv .venv```

source .venv/bin/activate

pip install -r requirements.txtor

cp .env.example .env

open -e .env```bash

```python prayonit_social.py --slot evening

```

Fill in the required keys (see below), then initialize the local database:

`--slot morning` schedules for the next 8:00 AM America/New_York time.

```bash`--slot evening` schedules for the next 7:00 PM America/New_York time.

python prayonit_social.py database-initIf `--slot` is omitted, it defaults to `morning`.

```

Each run generates a 1080x1350 feed image and a 1080x1920 Story image, and

## Environment variables(when `TEST_MODE=false`) queues five Buffer items: a Facebook feed post, an

Instagram feed post, a Facebook Story, an Instagram Story, and a Threads post,

Core (existing):all scheduled with `mode: customScheduled` for the selected slot.



- `GEMINI_API_KEY`The first images will appear under:

- `BUFFER_ACCESS_TOKEN`, and the per-platform Buffer profile IDs

- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY``output/`

- `TEST_MODE` — **must be `true`** while developing/testing

## Where to find the keys

New for v1.0 (see `.env.example` for full list and defaults):

- Gemini API key: Google AI Studio → API keys.

- `TRACKING_BASE_URL` — base URL used to build tracked links- Buffer key: Buffer → Settings → API → Personal Keys.

- `IOS_DESTINATION_URL`, `ANDROID_DESTINATION_URL`, `DEFAULT_DESTINATION_URL`- Supabase service-role key: Supabase project → Settings → API Keys.

- `TRACKING_SECRET` — used only to mix into tracking-id generation, never logged

- `METRICS_COOLDOWN_HOURS` — minimum hours between metrics re-checks (default 12)The Supabase service-role key is powerful. Keep `.env` private and never paste

- `HISTORY_AVOID_LAST_N_*` — non-repetition tuning for campaign/background historyit in chat, commit it to GitHub, or place it inside the Flutter app.



The Supabase service-role key and `TRACKING_SECRET` are sensitive. Never## Publishing

commit `.env`, never paste secrets in chat, and never log them.

After the local test image looks correct:

## Commands

1. Open `.env`.

```bash2. Change `TEST_MODE=true` to `TEST_MODE=false`.

# Safe, local-only commands (no network calls):3. Run `python prayonit_social.py --slot morning` (or `--slot evening`) again.

python prayonit_social.py campaigns          # list all loaded campaigns4. Confirm all five posts (Facebook post, Instagram post, Facebook Story,

python prayonit_social.py database-init      # create/upgrade local SQLite db   Instagram Story, Threads post) appear in Buffer, scheduled for the chosen

python prayonit_social.py history --days 30  # show recent run history   slot.



# Full run (dry run while TEST_MODE=true, live once TEST_MODE=false):Facebook and Instagram metadata (including `shouldShareToFeed`) are already

python prayonit_social.py run --slot morningincluded for both feed posts and Stories. If one platform/post-type fails,

python prayonit_social.py run --slot eveningthe script logs the error for that item only and continues with the rest,

# Legacy form (still supported):then prints a final success/failure summary.

python prayonit_social.py --slot morning

## Later scheduling

# Buffer analytics (see docs/BUFFER_ANALYTICS.md):

python prayonit_social.py discover-buffer-metricsOnce the local test works, move these same files to a private GitHub repository

python prayonit_social.py analytics --days 7and add a scheduled GitHub Actions workflow. Scheduled workflows support cron

```schedules and can run this script automatically in the morning and evening.


`--slot morning` schedules for the next 8:00 AM America/New_York time.
`--slot evening` schedules for the next 7:00 PM America/New_York time.

## What a `run` does

1. Selects a campaign, formula, persona, background image, and any active
   seasonal context via `campaign_engine.choose_selection()`, using local
   history to avoid recent repeats (see `docs/CAMPAIGN_BRAIN.md`).
2. Builds a tracked link for the destination URL (`tracking.py`).
3. Builds a Gemini prompt and generates ad copy + platform captions
   (`prompt_builder.py`).
4. Renders a 1080x1350 feed image and a 1080x1920 Story image
   (`image_renderer.py`) and saves them under `output/`.
5. If `TEST_MODE=true`, stops here — nothing is uploaded or scheduled.
6. If `TEST_MODE=false`: uploads both images to Supabase, then queues five
   Buffer items (Facebook feed, Instagram feed, Facebook Story, Instagram
   Story, Threads) with `mode: customScheduled` for the selected slot. Each
   platform/post-type is wrapped in its own try/except so one failure
   doesn't stop the others.
7. Records the run, each published post (or error), and the tracked link in
   the local SQLite database (`data/prayonit_marketing.db`).

## Local database

Location: `data/prayonit_marketing.db` (SQLite, created by `database-init`
or automatically on first `run`). Tables: `campaigns_used`,
`published_posts`, `post_metrics`, `tracking_links`, `tracking_clicks`.
This file is local-only and is not uploaded anywhere.

## Tracked links

See `docs/TRACKING.md`. Layer 1 (implemented): every post gets a unique
tracked URL recorded in `tracking_links`. Layer 2 (source-only, not
deployed): a Supabase Edge Function
(`supabase/functions/track-download/index.ts`) that would record clicks and
redirect to the real store link — deploy manually with the Supabase CLI
when ready; nothing is deployed automatically by this project.

## Buffer metrics / analytics

See `docs/BUFFER_ANALYTICS.md`. Run `discover-buffer-metrics` first to
introspect Buffer's actual GraphQL schema (saved to
`data/buffer_metrics_schema.json`) before any real metrics query is built —
field names are never guessed.

## Campaigns, formulas, personas, seasonality

See `docs/CAMPAIGN_BRAIN.md` for the full schema and how to add new
campaigns/formulas/personas, or regenerate the whole set via:

```bash
python scripts/generate_marketing_brain.py
```

## Non-repetition & holiday selection

`campaign_engine.py` checks recent local history before choosing a
campaign/background, and boosts weights for any campaign matching an active
seasonal context (holiday, Easter-relative date, nth-weekday holiday like
Mother's Day, or a season window). If exclusion rules would empty the
selection pool, they are gradually relaxed (logged, never a crash).

## Testing

Fully mocked — no live Gemini/Buffer/Supabase calls are made by the test
suite:

```bash
python -m pytest tests/ -q
```

## Troubleshooting

- **"Cannot find Deno" errors in `supabase/functions/track-download/index.ts`**
  — expected; this is Deno-runtime code with no local Deno types installed.
  It's only meant to be deployed via `supabase functions deploy`, not run
  locally with Python.
- **`analytics` reports no metrics** — run `discover-buffer-metrics` first
  and verify the schema in `data/buffer_metrics_schema.json`; the metrics
  query is intentionally not built until field names are confirmed.
- **A campaign/background repeats sooner than expected** — check
  `HISTORY_AVOID_LAST_N_*` in `.env` and confirm `data/prayonit_marketing.db`
  isn't being reset between runs.
- **Python version** — this project targets Python 3.9 compatibility
  (no `X | Y` unions, no `match` statements); see `test_python39_compat.py`.

## Safety reminders

- Keep `TEST_MODE=true` while developing. Only set it to `false`
  intentionally when you want live Buffer scheduling to happen.
- Never commit `.env` or paste secrets (Gemini key, Buffer token, Supabase
  service-role key, `TRACKING_SECRET`) anywhere.
- The Layer 2 Edge Function must be deployed manually — this project never
  runs `supabase functions deploy` or applies SQL migrations automatically.
