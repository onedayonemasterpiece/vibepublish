"""Bounded execution windows derived only from immutable verified plans."""


def execution_seconds(plan):
    assets = plan.get("assets", ())
    if (plan.get("provider") == "vk" and plan.get("surface") == "post"
            and plan.get("action") in {"publish", "edit"} and len(assets) > 1
            and all(a.get("role", "image") == "image"
                    and a.get("mime") in {"image/png", "image/jpeg", "image/webp"}
                    for a in assets)):
        return min(600, 90 * len(assets))
    if (plan.get("provider") == "telegram" and plan.get("workload") == "media_store"
            and any(a.get("role") == "document"
                    and a.get("mime") in {"application/pdf", "image/vnd.djvu"}
                    for a in assets)):
        # Exact source uploads need longer than 90s at measured Telegram rates.
        return min(600, max(90, (sum(a.get("size", 0) for a in assets) + 249_999) // 250_000))
    return 90


def command_seconds(plans):
    return max((execution_seconds(plan) + 30 for plan in plans), default=120)
