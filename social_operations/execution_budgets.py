"""Bounded execution windows derived only from immutable verified plans."""


def execution_seconds(plan):
    assets = plan.get("assets", ())
    if (plan.get("provider") == "vk" and plan.get("surface") == "post"
            and plan.get("action") in {"publish", "edit"} and len(assets) > 1
            and all(a.get("role", "image") == "image"
                    and a.get("mime") in {"image/png", "image/jpeg", "image/webp"}
                    for a in assets)):
        return min(600, 90 * len(assets))
    return 90


def command_seconds(plans):
    return max((execution_seconds(plan) + 30 for plan in plans), default=120)
