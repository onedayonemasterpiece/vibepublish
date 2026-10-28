# Bounded VK multi-photo execution budgets

Status: **Fixed** existing budget contract; **Not confirmed by user** for the current reliability correction until live acceptance.

A prior four-photo edit reached the ordinary 90-second execute cap after three successful saves, before `wall.edit`. For VK wall publish/edit with **two or more images**, retain the existing 90 seconds per photo, capped at **600 seconds execute**, plus a 30-second overhead within **630 seconds admission**. Single-photo and other actions retain 90 seconds execute / 120 seconds admission. Do not extend the absolute admitted deadline, native scheduling lead time, lease or recovery horizon. Observation-only reconciliation after dispatch retains its 90-second bound.

W2 changes only the photo-upload loop: up to **five attempts**, refreshed upload server, 1/2/3/4-second backoff on temporary failures. No changes to the above command budgets, the HTTP 25-second timeout, frozen assets, authority or dispatch fencing. Saved photo checkpoints avoid uploading already saved photos again. A passing fixture does not establish live VK delivery.
