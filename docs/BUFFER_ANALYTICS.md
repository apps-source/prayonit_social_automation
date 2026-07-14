# Buffer Analytics

## Why this is careful by design

Buffer's GraphQL metrics schema was not guessed. Instead:

1. `python prayonit_social.py discover-buffer-metrics` runs a GraphQL
   introspection query (schema only — no post data) and saves the raw result
   to `data/buffer_metrics_schema.json`.
2. A human (or a later, deliberate change) reads that file, confirms the
   exact `Post.metrics` field and its result type's field names.
3. Only then should `buffer_client.build_metrics_query_from_schema()` be
   extended to build a real metrics query, and `analytics.run_analytics()`
   will start actually populating `post_metrics`.

Until that verification step happens, `analytics` reports honestly that no
verified metrics query is available yet — it does not fabricate field names
or silently fail.

## Commands

```bash
python prayonit_social.py discover-buffer-metrics
python prayonit_social.py analytics --days 7
python prayonit_social.py analytics --days 30
```

## Cooldown

`history_store.get_posts_missing_metrics(cooldown_hours=...)` only returns
posts that:

- have a `buffer_post_id` (i.e. were actually scheduled, not failed),
- have `buffer_status = 'scheduled'`, and
- were not checked within the last `METRICS_COOLDOWN_HOURS` (default 12,
  configurable via `.env`).

## Report contents

- posts checked / updated / skipped / failures
- posts scheduled vs failed in the requested window
- metrics observations recorded in the requested window
- (once verified metric values exist) top campaigns, top platforms, top
  headlines, and morning-vs-evening breakdowns

## Failure handling

Each post's metrics fetch is wrapped in its own try/except; one failure is
logged and the loop continues.
