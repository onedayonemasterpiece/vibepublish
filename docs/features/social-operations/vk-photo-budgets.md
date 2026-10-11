# Bounded VK multi-photo execution budgets

Status: Not done until the corrected same-post carousel is verified live.

Observed defect: four-photo staging reached the generic90-second execute cap after three successful saves, before wall.edit. The ordinary command also had a120-second deadline. Per-upload25-second timeout and three transient upload attempts remain unchanged.

Fixed requirements:
- Keep single-photo and all other provider/action budgets unchanged:90seconds execute and120seconds admission.
- For VK post publish/edit with two or more image assets, allow90seconds per photo, capped at600seconds execute. The initial command and explicit safe recovery window include30seconds overhead, capped at630seconds.
- Always respect the admitted absolute deadline, lease/fence, native schedule lead time and existing no-repeat rules. Reconciliation after dispatch keeps its existing90-second bound.
- Do not increase HTTP timeout or retry count. Do not persist private upload capabilities, clear unknown results, change assets, or automatically rearm terminal operations.

An explicit VK HTTP502/503/504 is a separate upstream failure. This budget correction does not guarantee upload availability or restore partial staging from past attempts.
