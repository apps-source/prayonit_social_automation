# Tracked Links

## Layer 1 (implemented today)

For every `run`, `tracking.create_tracked_link()`:

1. Generates a short, random tracking id (`secrets.token_urlsafe` + a hash
   that mixes in `TRACKING_SECRET`, which is never logged or returned).
2. Builds a URL: `{TRACKING_BASE_URL}/download?t=<tracking_id>`.
3. Stores the mapping (run, campaign, formula, persona, platform, post type,
   slot, scheduled time, destination) in the local `tracking_links` SQLite
   table.
4. Passes the URL to Gemini so it's woven naturally into the Facebook,
   Instagram, and Threads captions.

This works today even without a live redirect endpoint — the link is stored
and logged so nothing is lost, but visiting it currently does whatever
`TRACKING_BASE_URL` currently resolves to (your existing Google Sites page)
until Layer 2 is deployed.

Story images never contain a raw tracked URL — only "Download Prayonit" text,
since Stories don't reliably support long visible links.

## Layer 2 (source-only; not deployed automatically)

`supabase/functions/track-download/index.ts` is a Supabase Edge Function
that, once deployed:

1. Accepts `GET /track-download?t=<id>&store=ios|android`.
2. Looks up the tracking id in the `social_tracking_links` table.
3. Records the click in `social_tracking_clicks`.
4. Redirects (302) to the correct App Store / Google Play / default URL.
5. Falls back safely to `DEFAULT_DESTINATION_URL` for unknown ids or errors.

### Deploying Layer 2 (manual steps)

See `supabase/functions/track-download/README.md` for the full command
sequence. In short:

```bash
supabase login
supabase link --project-ref <your-project-ref>
# apply supabase/migrations/0001_social_tracking.sql via SQL editor or:
supabase db push
supabase secrets set SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
  IOS_DESTINATION_URL=... ANDROID_DESTINATION_URL=... DEFAULT_DESTINATION_URL=...
supabase functions deploy track-download
```

After deployment, set `TRACKING_BASE_URL` in `.env` to the function's public
URL (or a custom domain in front of it) so newly generated tracked links
resolve through the Edge Function.

## What is NOT done automatically

- The Edge Function is never deployed by the Python automation.
- The SQL migration is never applied automatically.
- `TRACKING_SECRET` is read from `.env` but never printed, logged, or
  included in any generated URL.
