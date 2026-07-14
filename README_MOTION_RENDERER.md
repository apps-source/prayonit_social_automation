# Motion Renderer (Proof-of-Concept)

**Status: standalone, experimental, NOT part of production.**

`motion_renderer.py` proves that the existing Prayonit static ad
(logo → brand wordmark → headline → spiritual action → benefit → CTA button →
trial text → store badges) can be rendered as a fade-in animated overlay on
top of a moving MP4 background instead of a static image, using the same
visual language already approved in `image_renderer.py`.

It does **not** touch, import, or call any production file:
`prayonit_social.py`, `image_renderer.py`, `creative_engine_v3.py`,
`prompt_builder.py`, `buffer_client.py`, `history_store.py`, `tracking.py`,
`campaign_engine.py`, scheduling, QA, or Supabase. Running it has zero effect
on the live automation.

---

## 1. Architecture

```
assets/motion_backgrounds/*.mp4   →  random.choice() picks ONE clip
assets/branding/*.png              →  logo + App Store + Google Play badges
system fonts (DejaVu / Arial Bold) →  same font discovery logic as image_renderer.py

                    │
                    ▼
        _build_overlay_layers(width, height)
        builds 8 independent transparent RGBA
        "layers" (logo, wordmark, headline,
        spiritual action, benefit panel, CTA
        button, trial text, badge row), each
        with its own fade-in start time.
                    │
                    ▼
        VideoClip(make_frame, duration=...)
        For every output frame at time t:
          1. Grab the real background frame at time t (unmodified).
          2. For each layer, compute a 0.0-1.0 fade alpha from t.
          3. Alpha-composite each visible layer onto the frame
             at its fixed screen position.
          4. Return the composed RGB frame.
                    │
                    ▼
        write_videofile("output/videos/video_test.mp4")
        Same resolution, same FPS, same duration as the source
        clip. Audio (if the source has any) is passed through
        unchanged.
```

No frame is ever cropped, resized, retimed, or re-encoded at a different
frame rate — the overlay is drawn directly onto each original frame in
place.

## 2. Files used

| File | Role |
|---|---|
| `motion_renderer.py` | The entire proof-of-concept. Self-contained. |
| `assets/motion_backgrounds/*.mp4` | Source of the random moving background. |
| `assets/branding/prayonit_logo.png` | Logo layer (fades in first). |
| `assets/branding/app_store_badge.png` | Store badge row (right side). |
| `assets/branding/google_play_badge.png` | Store badge row (left side). |
| `output/videos/video_test.mp4` | Generated output (overwritten each run). |

## 2a. Output folder structure

Generated outputs across the project (both the static `image_renderer.py`
pipeline and this motion renderer) are organized under `output/` as follows:

```
output/
    images/
        feed/      <- final static Feed images (image_renderer.py / prayonit_social.py)
        story/     <- final static Story images (image_renderer.py / prayonit_social.py)
    videos/        <- final rendered MP4 videos (this file: video_test.mp4)
    previews/      <- optional preview files (GIF/JPEG/PNG/contact sheets)
    temp/          <- temporary overlays or intermediate rendering files
```

`motion_renderer.py` only writes to `output/videos/` (final video) and
would use `output/temp/` for any intermediate/overlay files (none are
currently produced, since the export is fully silent and in-memory). All
folders are created automatically via `Path.mkdir(parents=True,
exist_ok=True)` and resolve relative to the project root
(`Path(__file__).resolve().parent`), so this works regardless of the
terminal's current working directory. Pre-existing files directly under
`output/` from before this reorganization are left untouched as historical
files.

`image_renderer.py` is **read only as a design reference** — its font
discovery logic, color constants (white `#FFFFFF`, gold accent
`#FFE2A4`), CTA button styling (rounded rect, dark fill, white outline),
and benefit-panel styling (translucent rounded rectangle) were duplicated
into `motion_renderer.py` in isolation rather than imported, so production
code paths are never touched or affected by this file.

## 3. How rendering works

1. `_pick_random_motion_background()` globs `assets/motion_backgrounds/*.mp4`
   and picks one with `random.choice()`.
2. `VideoFileClip` opens it and reports its native `width`, `height`, `fps`,
   and `duration` — all of which are reused unchanged for the output.
3. `_build_overlay_layers()` renders each ad element as its own small RGBA
   image (matching image_renderer.py's Feed sizing/spacing proportionally,
   scaled by `width / 1080` so it looks correct at any source resolution),
   and assigns each a staggered fade-in start time (0.4s, 0.75s, 1.1s, ...
   0.35s apart) and a 0.6s fade duration. After fading in, each element
   stays fully opaque for the rest of the clip.
4. A single `VideoClip(make_frame, ...)` builds every output frame by:
   - reading the real background frame for that timestamp,
   - alpha-compositing each currently-visible layer (with its current fade
     alpha applied to its alpha channel) on top,
   - returning the flattened RGB frame.
5. `write_videofile()` encodes the result with `libx264` (and `aac` if the
   source had an audio track) at the source's original FPS.

No third-party video-editing dependency beyond `moviepy` (already declared
compatible with this project's Python 3.9 environment) was required;
`moviepy` bundles its own FFmpeg binary via `imageio-ffmpeg`, so no system
FFmpeg install was needed.

**New dependencies added:** `moviepy`, `imageio-ffmpeg` (installed into the
existing project venv only; not yet added to `requirements.txt`, since this
is a proof-of-concept and the task explicitly says not to integrate yet).

## 4. How to swap backgrounds

Just add or remove `.mp4` files in `assets/motion_backgrounds/`. Each run of
`python motion_renderer.py` picks a new random file from whatever is
currently in that folder — no code changes needed. To force a specific
background for testing, temporarily edit `_pick_random_motion_background()`
to return a fixed `Path` instead of `random.choice(candidates)`.

To change the overlay copy (headline, spiritual action, benefit, CTA text,
trial text), edit the `COPY` dict near the top of `motion_renderer.py`.

## 5. How to later plug this into `prayonit_social.py` (future phase)

This file is deliberately structured so a future integration requires only
**additive** changes, never modifications to existing rendering:

1. Keep `image_renderer.py` exactly as-is for static Feed/Story rendering.
2. Extract `_build_overlay_layers()` and `render_motion_ad()` into a proper
   module function that accepts `copy: Dict[str, str]` (the same ad-copy
   dict already produced by `prompt_builder.py` / `creative_engine_v3.py`)
   instead of the hardcoded `COPY` constant used here.
3. In `prayonit_social.py`, add a new, separate, opt-in code path (e.g. a
   `--motion` CLI flag or a `video_ad` campaign attribute) that calls the
   new motion-render function *in addition to* — not instead of — the
   existing `image_renderer.compose_ad()` / `compose_story_ad()` calls.
   The existing image pipeline, QA engine, and Buffer image posts remain
   completely untouched.
4. Buffer's video-post support (a distinct GraphQL mutation shape from
   image posts) would need its own small addition to `buffer_client.py` —
   again additive, not a modification of the existing
   `buffer_create_post()` image path.
5. QA: the existing `creative_engine_v3` contrast/headline validators
   operate on a single composed image; for video, the same validators can
   be run once against a representative fully-faded-in frame extracted
   from the output clip (e.g. the last frame), without any changes to the
   validator functions themselves.

Until that future phase is explicitly requested, `motion_renderer.py`
remains fully isolated and production continues to run exactly as it does
today.
