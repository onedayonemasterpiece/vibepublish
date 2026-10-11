"""Content-free instrumentation for MAX's existing awaited UI steps."""
from functools import wraps

from social_operations.provider_diagnostics import provider_call

from .profile import MaxBlocked


# Closed reasons from the instrumented leaf methods only. Never accept an
# arbitrary exception string, even if it resembles an identifier.
_SAFE_REASONS = frozenset({
    'candidate_changed_during_copy',
    'context_menu_already_open',
    'context_menu_route_changed',
    'context_menu_subject_changed',
    'existing_attachments',
    'existing_draft',
    'media_download_failed',
    'media_download_format',
    'media_download_size',
    'media_identity_unavailable',
    'media_post_reference_changed',
    'native_calendar_horizon',
    'native_calendar_unfamiliar',
    'native_context_menu_not_open',
    'native_copy_menu_unavailable',
    'native_non_link_text_surface_unavailable',
    'native_queue_content_changed',
    'native_queue_time_changed',
    'native_reference_scope_mismatch',
    'native_row_detached',
    'native_schedule_minute_precision',
    'native_schedule_status_unqualified',
    'needs_auth_or_wrong_account',
    'nonexact_plain_candidate',
    'rich_composer_mismatch',
    'rich_recipe_not_qualified',
    'rich_selection_changed',
    'unsupported_media',
    'unsupported_namespace',
    'upload_preview_mismatch',
    'video_source_unavailable',
    'wrong_namespace',
    'wrong_target_or_origin',
})


async def observe(operation, awaitable):
    """Observe exactly one await; preserve its return value and exception."""
    with provider_call("max", operation) as diagnostic:
        try:
            return await awaitable
        except MaxBlocked as exc:
            reason = str(exc)
            if reason in _SAFE_REASONS:
                diagnostic["error_code"] = reason
            raise


def observed(operation):
    """Instrument a shared async UI step without changing its call signature."""
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            return await observe(operation, function(*args, **kwargs))
        return call
    return decorate
