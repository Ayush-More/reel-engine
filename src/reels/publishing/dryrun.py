"""Dry-run publisher: shows the exact Graph API calls it WOULD make, never touches the network."""
from __future__ import annotations

from ..contracts.models import PublishPackage, PublishResult
from .base import Publisher


class DryRunPublisher(Publisher):
    mode = "dry_run"

    def publish(self, package: PublishPackage, reasons: list[str]) -> PublishResult:
        if reasons:
            return PublishResult(mode="dry_run", status="blocked", blocked_reasons=reasons)
        caption = package.caption + "\n\n" + " ".join(package.hashtags)
        plan = [
            {"step": 1, "call": "POST /{ig-user-id}/media",
             "params": {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                        "cover_url": package.cover_path, "share_to_feed": True}},
            {"step": 2, "call": "POST rupload.facebook.com/ig-api-upload/{container-id}", "file": package.video_path},
            {"step": 3, "call": "GET /{container-id}?fields=status_code", "poll_until": "FINISHED"},
            {"step": 4, "call": "POST /{ig-user-id}/media_publish", "params": {"creation_id": "{container-id}"}},
        ]
        return PublishResult(mode="dry_run", status="would_publish", detail={"plan": plan,
                             "idempotency_key": package.idempotency_key})


class InstagramPublisher(Publisher):  # Phase 3
    mode = "live"

    def publish(self, package: PublishPackage, reasons: list[str]) -> PublishResult:
        if reasons:
            return PublishResult(mode="live", status="blocked", blocked_reasons=reasons)
        raise NotImplementedError("Phase 3: implement container create, upload, poll, publish")
