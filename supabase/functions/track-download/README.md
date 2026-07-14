# track-download (Supabase Edge Function)

**Not deployed automatically.** This function is Layer 2 of tracked links
(see `docs/TRACKING.md`). It is source-only until you deploy it manually.

## What it does

`GET /track-download?t=<tracking_id>&store=ios|android`

1. Looks up `tracking_id` in `social_tracking_links`.
2. Records the click in `social_tracking_clicks`.
3. Redirects (HTTP 302) to the iOS/Android/default destination.
4. Falls back to `DEFAULT_DESTINATION_URL` if the tracking id is missing,
   invalid, or any step fails — it never surfaces an error to the visitor.
5. Never returns or logs `SUPABASE_SERVICE_ROLE_KEY`.

## One-time setup (manual)

1. Install the Supabase CLI: `brew install supabase/tap/supabase`
2. Log in: `supabase login`
3. Link the project: `supabase link --project-ref <your-project-ref>`
4. Apply the SQL migration in `supabase/migrations/0001_social_tracking.sql`
   (via the Supabase SQL editor, or `supabase db push`).
5. Set the function's secrets (separate from your local `.env`):

   ```bash
   supabase secrets set \
     SUPABASE_URL=https://<project-ref>.supabase.co \
     SUPABASE_SERVICE_ROLE_KEY=<service-role-key> \
     IOS_DESTINATION_URL=<app-store-url> \
     ANDROID_DESTINATION_URL=<play-store-url> \
     DEFAULT_DESTINATION_URL=https://prayonit.nextwavestudiosapp.com
   ```

6. Deploy: `supabase functions deploy track-download`

## Testing after deployment

```bash
curl -i "https://<project-ref>.functions.supabase.co/track-download?t=someid&store=ios"
```

Expect an HTTP 302 with a `Location` header pointing at the resolved
destination.
