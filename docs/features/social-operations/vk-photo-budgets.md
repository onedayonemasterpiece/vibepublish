# Bounded VK multi-photo execution budgets

Status: Not done until the corrected same-post carousel is verified live.

Observed defect: four-photo staging reached the generic 90-second execute cap after three successful saves, before wall.edit. The ordinary command also had a 120-second deadline. Per-upload 25-second timeout and three transient upload attempts remain unchanged.

Fixed requirements:
- Keep single-photo and all other provider/action budgets unchanged: 90 seconds execute and 120 seconds admission.
- For VK post publish/edit with two or more image assets, allow 90 seconds per photo, capped at 600 seconds execute. The initial command and explicit safe recovery window include 30 seconds overhead, capped at 630 seconds.
- Always respect the admitted absolute deadline, lease/fence, native schedule lead time and existing no-repeat rules. Reconciliation after dispatch keeps its existing 90-second bound.
- Do not increase HTTP timeout or retry count. Do not persist private upload capabilities, clear unknown results, change assets, or automatically rearm terminal operations.

An explicit VK HTTP502/503/504 is a separate upstream failure. This budget correction does not guarantee upload availability or restore partial staging from past attempts.

## §18.1 / W2 policy update (2026-10-27)

**No budget changes from W2.** The existing per-photo 90s / 600s cap and 630s admission remain. W2 changes (5 retries, 429 retry, no CDN fingerprint) operate within these bounds.