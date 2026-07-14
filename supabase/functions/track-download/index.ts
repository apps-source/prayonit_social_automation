// Supabase Edge Function: track-download
//
// NOT DEPLOYED AUTOMATICALLY. See README.md in this folder for manual
// deployment steps.
//
// GET /track-download?t=<tracking_id>&store=ios|android|default
//   1. Validates that the tracking_id exists in social_tracking_links.
//   2. Records the click in social_tracking_clicks.
//   3. Redirects (HTTP 302) to the correct destination for the given store.
//   4. Falls back to a safe default destination if the tracking_id is
//      missing or invalid, and never throws an unhandled error to the client.
//
// The Supabase service-role key is read only from the Edge Function's own
// environment (set via `supabase secrets set`) and is never returned to the
// caller or included in the redirect URL.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const IOS_DESTINATION_URL = Deno.env.get("IOS_DESTINATION_URL") ?? "";
const ANDROID_DESTINATION_URL = Deno.env.get("ANDROID_DESTINATION_URL") ?? "";
const DEFAULT_DESTINATION_URL = Deno.env.get("DEFAULT_DESTINATION_URL") ?? "https://prayonit.nextwavestudiosapp.com";

function resolveDestination(store: string | null, linkDestination: string | null): string {
  if (store === "ios" && IOS_DESTINATION_URL) return IOS_DESTINATION_URL;
  if (store === "android" && ANDROID_DESTINATION_URL) return ANDROID_DESTINATION_URL;
  if (linkDestination) return linkDestination;
  return DEFAULT_DESTINATION_URL;
}

Deno.serve(async (req: Request) => {
  try {
    const url = new URL(req.url);
    const trackingId = url.searchParams.get("t");
    const store = url.searchParams.get("store");
    const userAgent = req.headers.get("user-agent") ?? "";
    const referrer = req.headers.get("referer") ?? "";

    if (!trackingId) {
      return Response.redirect(DEFAULT_DESTINATION_URL, 302);
    }

    // Service-role client is created per-request from function-scoped secrets
    // only; it is never exposed to the caller.
    const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    const { data: link, error } = await supabase
      .from("social_tracking_links")
      .select("tracking_id, destination, platform")
      .eq("tracking_id", trackingId)
      .maybeSingle();

    if (error || !link) {
      // Invalid/unknown tracking id: safe fallback, no error surfaced.
      return Response.redirect(DEFAULT_DESTINATION_URL, 302);
    }

    const destination = resolveDestination(store, link.destination);

    // Record the click. Failure to record must never block the redirect.
    try {
      await supabase.from("social_tracking_clicks").insert({
        tracking_id: trackingId,
        platform: link.platform,
        destination,
        user_agent: userAgent,
        referrer,
      });
    } catch (_clickError) {
      // Intentionally swallowed; redirect must still succeed.
    }

    return Response.redirect(destination, 302);
  } catch (_unexpectedError) {
    return Response.redirect(DEFAULT_DESTINATION_URL, 302);
  }
});
