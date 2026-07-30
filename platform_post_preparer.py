"""Prepare validated public platform posts before Buffer serialization."""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HASHTAG_REGISTRY_PATH = (
    PROJECT_ROOT / "creative" / "hashtag_profiles.json"
)
DEFAULT_DIAGNOSTIC_DIR = (
    PROJECT_ROOT / "output" / "validation" / "sprint3d_platform_metadata"
)
SUPPORTED_PLATFORMS = {"facebook", "instagram", "tiktok"}
SUPPORTED_TIKTOK_OPTIONS = {"title", "isAiGenerated"}
UNSUPPORTED_TIKTOK_OPTIONS = {
    "privacy",
    "disableComments",
    "disableDuet",
    "disableStitch",
    "commercialContent",
    "brandOrganic",
    "postType",
}
PLATFORM_CAPTION_LIMITS = {
    "facebook": 5000,
    "instagram": 2200,
    "tiktok": 2200,
}
HASHTAG_PATTERN = re.compile(r"#[A-Za-z0-9_]+")
URL_PATTERN = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)
LINK_IN_BIO_PATTERN = re.compile(
    r"\blink\s+in\s+(?:the\s+)?bio\b[.!?]*",
    flags=re.IGNORECASE,
)
CTA_EQUIVALENT_PATTERN = re.compile(
    r"\b(?:"
    r"download\s+prayonit\s+and\s+pray\s+with\s+me"
    r"|come\s+pray\s+with\s+(?:me|us)"
    r"|join\s+(?:me|us)\s+in\s+prayer"
    r"|pray\s+with\s+me(?:\s+today)?"
    r")\b[.!?]*",
    flags=re.IGNORECASE,
)
ABSOLUTE_LOCAL_PATH_PATTERN = re.compile(
    r"(?:^|\s)(?:/[A-Za-z0-9._~-]+/|[A-Za-z]:\\)",
)


class PlatformPostPreparationError(ValueError):
    """Raised when public platform metadata is unsafe or malformed."""


@dataclass(frozen=True)
class PreparedPlatformPost:
    platform: str
    public_caption: str
    hashtags: Tuple[str, ...]
    cta_text: str
    scheduled_at: str
    media_reference: Optional[str]
    post_type: str
    platform_options: Dict[str, Any]
    internal_metadata: Dict[str, Any]
    cta_diagnostics: Dict[str, Any]
    hashtag_minimum: int
    hashtag_maximum: int

    def with_delivery(
        self,
        *,
        post_type: str,
        media_reference: str,
    ) -> "PreparedPlatformPost":
        if post_type == "story":
            return replace(
                self,
                public_caption="",
                hashtags=(),
                cta_text="",
                post_type=post_type,
                media_reference=media_reference,
                hashtag_minimum=0,
                hashtag_maximum=0,
            )
        return replace(
            self,
            post_type=post_type,
            media_reference=media_reference,
        )

    def validate(self, *, require_media: bool = True) -> None:
        validate_prepared_post(self, require_media=require_media)

    def to_persistence_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "public_caption": self.public_caption,
            "hashtags": list(self.hashtags),
            "cta_text": self.cta_text,
            "scheduled_at": self.scheduled_at,
            "media_reference": self.media_reference,
            "post_type": self.post_type,
            "supported_platform_options": self.platform_options,
            "internal_metadata": self.internal_metadata,
            "cta_diagnostics": self.cta_diagnostics,
        }


def load_hashtag_registry(
    path: Path = DEFAULT_HASHTAG_REGISTRY_PATH,
) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlatformPostPreparationError(
            f"Hashtag profile registry is missing: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise PlatformPostPreparationError(
            f"Hashtag profile registry is malformed: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise PlatformPostPreparationError(
            "Hashtag profile registry must contain a profiles object."
        )
    return data


def _clean_spacing(text: str) -> str:
    cleaned = re.sub(r"[ \t]+", " ", text or "")
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+([,;:])", r"\1", cleaned)
    cleaned = re.sub(r"(^|\n)\s*[.!?]+\s*(?=\n|$)", r"\1", cleaned)
    return cleaned.strip(" \n,;:-")


def _remove_public_fragments(text: str) -> Tuple[str, Dict[str, int]]:
    hashtag_count = len(HASHTAG_PATTERN.findall(text or ""))
    url_count = len(URL_PATTERN.findall(text or ""))
    link_count = len(LINK_IN_BIO_PATTERN.findall(text or ""))
    cta_count = len(CTA_EQUIVALENT_PATTERN.findall(text or ""))
    cleaned = HASHTAG_PATTERN.sub("", text or "")
    cleaned = URL_PATTERN.sub("", cleaned)
    cleaned = LINK_IN_BIO_PATTERN.sub("", cleaned)
    cleaned = CTA_EQUIVALENT_PATTERN.sub("", cleaned)
    return _clean_spacing(cleaned), {
        "cta_duplicates_removed": cta_count,
        "link_in_bio_duplicates_removed": link_count,
        "url_duplicates_removed": url_count,
        "preexisting_hashtags_removed": hashtag_count,
    }


def _resolve_hashtags(
    *,
    profile_id: str,
    prayer_category_id: str,
    platform: str,
    seed: str,
    registry: Mapping[str, Any],
) -> Tuple[Tuple[str, ...], int, int]:
    profile = registry["profiles"].get(profile_id)
    if not isinstance(profile, dict):
        raise PlatformPostPreparationError(
            f"Unknown hashtag profile ID: {profile_id}"
        )
    limits = (profile.get("platform_limits") or {}).get(platform)
    if not isinstance(limits, dict):
        raise PlatformPostPreparationError(
            f"Hashtag profile {profile_id} has no {platform} policy."
        )
    category_packs = profile.get("category_hashtags") or {}
    fallback_id = str(profile.get("fallback_category", "general_prayer"))
    category_pack = category_packs.get(
        prayer_category_id,
        category_packs.get(fallback_id),
    )
    if not isinstance(category_pack, dict):
        raise PlatformPostPreparationError(
            f"Hashtag profile {profile_id} has no usable category pack."
        )
    pool = list(dict.fromkeys(category_pack.get(platform) or ()))
    minimum = int(limits["minimum"])
    maximum = int(limits["maximum"])
    selected_count = min(int(limits["selected"]), len(pool), maximum)
    if selected_count < minimum:
        raise PlatformPostPreparationError(
            f"Hashtag profile {profile_id}/{prayer_category_id}/{platform} "
            "does not satisfy its minimum count."
        )
    if "#Prayonit" in pool and selected_count:
        remaining = [tag for tag in pool if tag != "#Prayonit"]
        rng = random.Random(
            f"{seed}:{profile_id}:{prayer_category_id}:{platform}"
        )
        selected = rng.sample(remaining, k=selected_count - 1)
        selected.append("#Prayonit")
    else:
        rng = random.Random(
            f"{seed}:{profile_id}:{prayer_category_id}:{platform}"
        )
        selected = rng.sample(pool, k=selected_count)
    return tuple(selected), minimum, maximum


def _internal_metadata(
    brief: Any,
    selected_asset_ids: Iterable[str],
) -> Dict[str, Any]:
    fields = (
        "prayer_category_id",
        "hook_profile_id",
        "voice_profile_id",
        "body_profile_id",
        "caption_profile_id",
        "scene_profile_id",
        "cta_profile_id",
        "hashtag_profile_id",
        "creative_policy_version",
    )
    return {
        **{
            field_name: str(getattr(brief, field_name, "") or "")
            for field_name in fields
        },
        "selected_asset_ids": [
            str(asset_id) for asset_id in selected_asset_ids if str(asset_id)
        ],
    }


def prepare_platform_post(
    *,
    platform: str,
    base_caption: str,
    brief: Any,
    scheduled_at: str,
    post_type: str,
    media_reference: Optional[str] = None,
    direct_url: Optional[str] = None,
    selected_asset_ids: Sequence[str] = (),
    hashtag_registry: Optional[Mapping[str, Any]] = None,
) -> PreparedPlatformPost:
    platform_id = platform.strip().lower()
    if platform_id not in SUPPORTED_PLATFORMS:
        raise PlatformPostPreparationError(
            f"Unsupported publishing platform: {platform}"
        )
    profile_id = str(getattr(brief, "hashtag_profile_id", "") or "")
    category_id = str(
        getattr(brief, "prayer_category_id", "general_prayer")
        or "general_prayer"
    )
    seed = str(getattr(brief, "run_id", "") or "platform-post")
    registry = hashtag_registry or load_hashtag_registry()
    hashtags, hashtag_minimum, hashtag_maximum = _resolve_hashtags(
        profile_id=profile_id,
        prayer_category_id=category_id,
        platform=platform_id,
        seed=seed,
        registry=registry,
    )
    body, removals = _remove_public_fragments(base_caption)
    canonical_cta = config.FACEBOOK_CTA
    parts = [body, canonical_cta]
    if platform_id == "facebook":
        destination = str(direct_url or "").strip()
        if destination:
            parts.append(destination)
    elif platform_id == "instagram":
        parts.append("Link in bio.")
    elif config.TIKTOK_INCLUDE_LINK_IN_BIO:
        parts.append("Link in bio.")
    parts.append(" ".join(hashtags))
    public_caption = "\n\n".join(part for part in parts if part).strip()
    platform_options: Dict[str, Any] = {}
    if platform_id == "tiktok":
        title_source = str(
            getattr(brief, "life_moment_text", "")
            or getattr(brief, "prayer_category_id", "")
            or "Prayer"
        ).strip()
        platform_options = {
            "title": title_source[:100],
            "isAiGenerated": True,
        }
    prepared = PreparedPlatformPost(
        platform=platform_id,
        public_caption=public_caption,
        hashtags=hashtags,
        cta_text=canonical_cta,
        scheduled_at=scheduled_at,
        media_reference=media_reference,
        post_type=post_type,
        platform_options=platform_options,
        internal_metadata=_internal_metadata(brief, selected_asset_ids),
        cta_diagnostics={
            "cta_source_retained": "canonical_platform_cta",
            **removals,
        },
        hashtag_minimum=hashtag_minimum,
        hashtag_maximum=hashtag_maximum,
    )
    prepared.validate(require_media=media_reference is not None)
    return prepared


def validate_prepared_post(
    post: PreparedPlatformPost,
    *,
    require_media: bool = True,
) -> None:
    errors = []
    if post.platform not in SUPPORTED_PLATFORMS:
        errors.append("platform is not recognized")
    if post.post_type != "story" and not post.public_caption.strip():
        errors.append("public caption is empty")
    if len(post.public_caption) > PLATFORM_CAPTION_LIMITS.get(
        post.platform, 0
    ):
        errors.append("public caption exceeds platform safety limit")
    if post.post_type != "story":
        cta_count = len(
            CTA_EQUIVALENT_PATTERN.findall(post.public_caption)
        )
        if cta_count != 1:
            errors.append(f"CTA must appear exactly once; found {cta_count}")
    if len(post.hashtags) < post.hashtag_minimum:
        errors.append("hashtag count is below profile minimum")
    if len(post.hashtags) > post.hashtag_maximum:
        errors.append("hashtag count exceeds profile maximum")
    if len(set(tag.lower() for tag in post.hashtags)) != len(post.hashtags):
        errors.append("duplicate hashtag tokens are not allowed")
    if any(
        not re.fullmatch(r"#[A-Za-z0-9_]+", tag)
        for tag in post.hashtags
    ):
        errors.append("hashtag format is invalid")
    if ABSOLUTE_LOCAL_PATH_PATTERN.search(post.public_caption):
        errors.append("public caption contains an absolute local path")
    if post.platform == "instagram" and URL_PATTERN.search(
        post.public_caption
    ):
        errors.append("Instagram public caption contains a raw URL")
    if post.platform == "facebook" and LINK_IN_BIO_PATTERN.search(
        post.public_caption
    ):
        errors.append("Facebook public caption contains link-in-bio wording")
    if len(URL_PATTERN.findall(post.public_caption)) > 1:
        errors.append("public caption contains duplicate URLs")
    public_text = " ".join(
        [
            post.public_caption,
            str(post.platform_options.get("title", "")),
            " ".join(post.hashtags),
        ]
    ).lower()
    for field_name, value in post.internal_metadata.items():
        if field_name.endswith("_profile_id") and value:
            if str(value).lower() in public_text:
                errors.append(
                    f"internal profile value leaked publicly: {field_name}"
                )
    if post.platform == "tiktok":
        unsupported = set(post.platform_options) - SUPPORTED_TIKTOK_OPTIONS
        if unsupported:
            errors.append(
                "unsupported TikTok options: " + ", ".join(sorted(unsupported))
            )
        if post.platform_options.get("isAiGenerated") is not True:
            errors.append("TikTok AI-generated disclosure must remain enabled")
    elif post.platform_options:
        errors.append("unsupported platform options were supplied")
    try:
        datetime.fromisoformat(post.scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        errors.append("scheduled time is not valid ISO 8601")
    if require_media:
        media = str(post.media_reference or "")
        parsed = urlparse(media)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("required public media URL is missing or invalid")
    if errors:
        raise PlatformPostPreparationError(
            f"Prepared {post.platform}/{post.post_type} post is invalid: "
            + "; ".join(errors)
        )


def resolve_publishing_status(
    *,
    intended_count: int,
    success_count: int,
    failure_count: int,
) -> str:
    if intended_count <= 0:
        return "prepared"
    if success_count > 0 and failure_count > 0:
        return "partially_published"
    if failure_count > 0 and success_count == 0:
        return "failed"
    if success_count == intended_count and failure_count == 0:
        return "published"
    return "publishing"


def write_validation_report(
    *,
    output_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
) -> Path:
    """Write deterministic preparation and payload fixtures without I/O."""
    import buffer_client

    categories = (
        "morning_prayer",
        "anxiety",
        "protection",
        "bible_verse",
        "general_prayer",
    )
    prepared_examples: Dict[str, Any] = {}
    for category in categories:
        brief = SimpleNamespace(
            run_id=f"sprint3d-{category}",
            prayer_category_id=category,
            life_moment_text=f"Representative {category.replace('_', ' ')} need",
            hook_profile_id="diagnostic_internal_hook",
            voice_profile_id="diagnostic_internal_voice",
            body_profile_id="diagnostic_internal_body",
            caption_profile_id="diagnostic_internal_caption",
            scene_profile_id="diagnostic_internal_scene",
            cta_profile_id="current_default",
            hashtag_profile_id="current_default",
            creative_policy_version="1",
        )
        category_posts: Dict[str, Any] = {}
        for platform in ("tiktok", "instagram", "facebook"):
            base_caption = (
                "God is near in this moment.\n\n"
                "Come pray with us. Join me in prayer.\n\n"
                "Link in bio. https://unapproved.example\n\n"
                "#OldTag #OldTag"
            )
            post = prepare_platform_post(
                platform=platform,
                base_caption=base_caption,
                brief=brief,
                scheduled_at="2026-07-30T12:00:00Z",
                post_type="video" if platform == "tiktok" else "reel",
                media_reference="https://cdn.example/prayonit-video.mp4",
                direct_url=(
                    "https://prayonit.app"
                    if platform == "facebook"
                    else None
                ),
                selected_asset_ids=("diagnostic-asset-1",),
            )
            payload = buffer_client.build_create_post_input(
                channel_id=f"mock-{platform}-channel",
                caption=post.public_caption,
                service=platform,
                post_type=post.post_type,
                due_at_iso=post.scheduled_at,
                video_url=post.media_reference,
                platform_options=post.platform_options,
            )
            category_posts[platform] = {
                "prepared_post": post.to_persistence_dict(),
                "mocked_buffer_input": payload,
            }
        prepared_examples[category] = category_posts

    report = {
        "report_version": "1",
        "prepared_examples": prepared_examples,
        "buffer_support": {
            "tiktok_supported_fields": sorted(SUPPORTED_TIKTOK_OPTIONS),
            "tiktok_unsupported_or_unverified_fields": sorted(
                UNSUPPORTED_TIKTOK_OPTIONS
            ),
            "preserved_defaults": [
                "privacy unchanged",
                "comments behavior unchanged",
                "Duet behavior unchanged",
                "Stitch behavior unchanged",
                "commercial-content behavior unchanged",
            ],
        },
        "simulated_publishing_statuses": {
            "full_success": resolve_publishing_status(
                intended_count=3,
                success_count=3,
                failure_count=0,
            ),
            "partial_success": resolve_publishing_status(
                intended_count=3,
                success_count=2,
                failure_count=1,
            ),
            "full_failure": resolve_publishing_status(
                intended_count=3,
                success_count=0,
                failure_count=3,
            ),
            "no_publishing_attempted": resolve_publishing_status(
                intended_count=0,
                success_count=0,
                failure_count=0,
            ),
        },
        "retry_behavior": {
            "successful_jobs": "skipped using original Buffer post ID",
            "failed_or_missing_jobs": "eligible for one normal rerun",
            "duplicate_successful_posts": "not submitted",
        },
        "external_calls_occurred": False,
    }
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "platform_metadata_validation.json"
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    print(write_validation_report())
