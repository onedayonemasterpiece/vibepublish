"""Golden task corpus, not model-generated calls or evidence of runtime behavior.

Render machine-readable JSON: python contracts/task_corpus_v1.py
"""
import json

ASSET = {"source": {"kind": "asset", "id": "asset_1"}}
ASSET2 = {"source": {"kind": "asset", "id": "asset_2"}}
TEXT = {"text": "Открытие сезона — 6 сентября в 12:00."}
AT = {"kind": "at", "at": "2026-09-06T12:00:00+02:00"}
JOBS = []


def job(text, tool, args, expect="accept_after_runtime_checks"):
    JOBS.append({"id": f"J{len(JOBS)+1:03d}", "user_job": text,
                 "tool": "vibepublish_" + tool, "arguments": args,
                 "runtime_oracle": expect})


def publish(text, **kw):
    job(text, "publish", {"to": ["pka"], "content": TEXT, **kw})


def update(text, change, expect="accept_after_runtime_checks"):
    job(text, "publication_update", {"publication_id": "pub_1",
        "expected_revision": 2, "change": change}, expect)


job("Покажи инструкцию и доступные каналы", "get_started", {})
job("Покажи примеры вызовов", "get_started", {"section": "examples"})
job("Покажи возможности работы с картинками", "get_started", {"section": "visuals"})
publish("Опубликуй текст в телеграм-канале", to=["pka_tg"])
publish("Опубликуй текст в группе ВК", to=["pka_vk"])
publish("Опубликуй текст в MAX через веб", to=["pka_max"])
publish("Размести анонс во всём наборе Основные анонсы")
publish("Размести в Telegram и VK", to=["pka_tg", "pka_vk"])
publish("Поставь на 6 сентября в полдень по Калининграду", delivery=AT)
publish("Сохрани только превью, не публикуй", mode="preview")
publish("Опубликуй с одной картинкой", media=[ASSET])
publish("Опубликуй две картинки в этом порядке", media=[ASSET, ASSET2])
publish("Опубликуй видео с подписью", media=[{**ASSET, "role": "video"}], surface="video")
publish("Покажи фото в сторис", surface="story", media=[ASSET])
publish("Покажи видео в сторис", surface="story", media=[{**ASSET, "role": "video"}])
publish("Опубликуй альбом", surface="album", media=[ASSET, ASSET2])
publish("Отправь анонс мне в избранное Telegram", to=["owner_saved"], surface="message")
publish("Отправь согласованный текст партнёру", to=["partner_dm"], surface="message")
publish("Размести документ", media=[{**ASSET, "role": "document"}])
publish("Размести аудиофайл", media=[{**ASSET, "role": "audio"}])
publish("Размести анимацию", media=[{**ASSET, "role": "animation"}])
publish("Для Telegram сделай название ссылкой, в ВК покажи адрес", renderings={
    "telegram": {"paragraphs": [[{"kind": "link", "label": "Программа", "url": "https://example.org/event"}]]},
    "vk": {"text": "Программа: https://example.org/event"}})
publish("Используй проверенную картинку по HTTPS", media=[{"source": {"kind": "url", "url": "https://example.org/photo.jpg"}}])
publish("Используй вложение, уже переданное приложением", media=[{"source": {"kind": "upload", "ticket": "upload_1"}}])
publish("Создай иллюстрацию автоматически и размести", visual={"kind": "generate", "brief": "Музыка и осень, без букв", "selection": "automatic"})
publish("Сначала дай выбрать одну из двух иллюстраций", visual={"kind": "generate", "brief": "Филармония осенью", "candidates": 2, "selection": "human"})
publish("Улучши мой черновик карточки перед публикацией", visual={"kind": "tune", "source": ASSET, "brief": "Сохрани подтверждённый текст, улучши композицию"})
publish("Скомпонуй две фотографии для поста", visual={"kind": "compose", "sources": [ASSET, ASSET2], "brief": "Афиша без новых фактов"})
job("Создай отдельную иллюстрацию, не публикуй", "visual", {"command": {"kind": "generate", "brief": "Музыкальное настроение"}})
job("Улучши отдельную карточку", "visual", {"command": {"kind": "tune", "source": ASSET, "brief": "Больше воздуха"}})
job("Сделай композицию из двух картинок отдельно", "visual", {"command": {"kind": "compose", "sources": [ASSET, ASSET2], "brief": "Вертикальная композиция"}})
job("Выбираю второй вариант; продолжи исходную публикацию", "visual", {"command": {"kind": "select", "job_id": "visual_1", "candidate_id": "candidate_2", "expected_revision": 2, "token": "review_token"}})
job("Второй вариант не понравился из-за мелкого текста", "visual", {"command": {"kind": "feedback", "job_id": "visual_1", "candidate_id": "candidate_2", "rating": "rejected", "reason": "Мелкий текст"}})
update("Одобряю точное превью", {"kind": "approve", "token": "approval_token"})
update("Исправь текст существующей публикации", {"kind": "edit", "content": {"text": "Начало в 13:00."}})
update("Замени медиа в существующей публикации", {"kind": "edit", "media": [ASSET2]})
update("Перенеси отложенную публикацию", {"kind": "reschedule", "delivery": {"kind": "at", "at": "2026-09-06T13:00:00+02:00"}})
update("Отмени ещё не отправленный пост", {"kind": "cancel"})
update("Удали уже опубликованный пост", {"kind": "delete"})
update("Повтори только точно не отправившийся VK", {"kind": "retry_failed", "destinations": ["pka_vk"]})
job("Соединение оборвалось: что стало с публикацией?", "status", {"ids": ["op_1"]})
job("Проверь результат после перезапуска сервиса", "status", {"ids": ["pub_1"]})
job("Покажи последние мои операции", "status", {"limit": 10})
job("Продолжи список операций", "status", {"cursor": "cursor_1", "limit": 10})
job("Прочитай конкретный пост по ссылке", "read", {"query": {"kind": "item", "item_ref": "https://t.me/example/10"}})
job("Покажи доступные владельцу диалоги Telegram", "read", {"query": {"kind": "dialogs", "provider": "telegram"}})
for kind, text in [("feed", "Прочитай свежие посты канала"), ("stories", "Покажи текущие сторис"),
                   ("scheduled", "Покажи отложенные посты провайдера"), ("notifications", "Покажи уведомления"),
                   ("audience", "Покажи статистику аудитории"), ("editorial_sample", "Дай редакционную выборку")]:
    job(text, "read", {"query": {"kind": kind, "destination": "pka_tg"}, "limit": 10})
job("Найди посты о музыке в разрешённом канале", "read", {"query": {"kind": "search", "destination": "pka_tg", "text": "музыка"}})
job("Прочитай обсуждение поста", "read", {"query": {"kind": "thread", "item_ref": "item_1"}})
job("Посчитай реакции на пост", "read", {"query": {"kind": "reactions", "item_ref": "item_1"}})
job("Дай аналитику канала за сутки", "read", {"query": {"kind": "analytics", "destination": "pka_tg", "from": "2026-09-03T00:00:00Z", "to": "2026-09-04T00:00:00Z"}})
job("Ответь на выбранный комментарий", "engage", {"command": {"kind": "reply", "item_ref": "item_1", "content": {"text": "Спасибо!"}}})
job("Поставь реакцию", "engage", {"command": {"kind": "react", "item_ref": "item_1", "reaction": "👍", "mode": "add"}})
job("Убери свою реакцию", "engage", {"command": {"kind": "react", "item_ref": "item_1", "reaction": "👍", "mode": "remove"}})
job("Перешли пост в избранное", "engage", {"command": {"kind": "forward", "item_ref": "item_1", "to": ["owner_saved"]}})
job("Покажи мои разрешённые назначения", "destinations", {"command": {"kind": "list"}})
job("Разреши ссылку Telegram в точное назначение без выдачи прав", "destinations", {"command": {"kind": "resolve", "provider": "telegram", "url": "https://t.me/example"}})
job("Найди видимый владельцу канал", "destinations", {"command": {"kind": "search", "provider": "telegram", "text": "Анонсы"}})
job("Создай набор из трёх разрешённых каналов", "destinations", {"command": {"kind": "set_put", "alias": "pka", "label": "Основные анонсы", "expected_revision": 0, "members": ["pka_tg", "pka_vk", "pka_max"]}})
job("Удали MAX из набора, сохранив два канала", "destinations", {"command": {"kind": "set_put", "alias": "pka", "label": "Основные анонсы", "expected_revision": 2, "members": ["pka_tg", "pka_vk"]}})
job("Переименуй подпись набора, не меняя стабильный alias", "destinations", {"command": {"kind": "rename_label", "alias": "pka", "label": "Анонсы региона", "expected_revision": 3}})
job("Удали набор, не удаляя опубликованные посты", "destinations", {"command": {"kind": "set_delete", "alias": "pka", "expected_revision": 4}})
# Valid grammar deliberately does not imply authorization or a safe provider action.
job("Внешний пользователь просит чужую ленту", "read", {"query": {"kind": "feed", "destination": "other_tenant"}}, "deny_before_provider_read")
job("Внешний пользователь без read grant читает собственный канал", "read", {"query": {"kind": "feed", "destination": "own_channel"}}, "deny_before_provider_read")
job("Использовать чужой asset по известному идентификатору", "publish", {"to": ["pka"], "media": [{"source": {"kind": "asset", "id": "asset_other"}}]}, "deny_before_asset_or_provider_io")
job("Выбрать чужой кандидат картинки", "visual", {"command": {"kind": "select", "job_id": "visual_other", "candidate_id": "candidate_other", "expected_revision": 1, "token": "wrong_token"}}, "deny_before_parent_resume")
update("Повторить MAX после неопределённого клика", {"kind": "retry_failed", "destinations": ["pka_max"]}, "reject_uncertain_retry_keep_existing_receipt")
job("Повтор того же запроса с тем же ключом", "publish", {"to": ["pka"], "content": TEXT, "request_key": "same-key"}, "return_existing_receipt_no_new_dispatch")
job("Изменённый текст с уже использованным ключом", "publish", {"to": ["pka"], "content": {"text": "Другой текст"}, "request_key": "same-key"}, "idempotency_conflict_before_dispatch")
job("Намеренно повторить прежний пост по новому указанию", "publish", {"to": ["pka"], "content": TEXT, "request_key": "new-key", "repeat_of": "pub_1"}, "require_explicit_repeat_authority")
job("Публикация по собственному разрешённому подключению", "publish", {"to": ["tenant_own"], "content": TEXT}, "intersect_own_binding_grant_provider_rights")
job("Публикация партнёра через учётную запись оператора", "publish", {"to": ["partner_bound"], "content": TEXT}, "require_owner_created_exact_binding")
job("Уведомление об отмене события от EventsBot", "publication_update", {"publication_id": "pub_1", "expected_revision": 2, "change": {"kind": "edit", "content": {"text": "Событие отменено."}}, "request_key": "event-cancel-1"}, "event_domain_stays_in_client")
job("Убери подпись, оставь фотографию", "publication_update", {"publication_id": "pub_1", "expected_revision": 2, "change": {"kind": "edit", "content": {"text": ""}}}, "nonempty_media_required_after_edit")
job("Пустой пост не должен отправиться", "publish", {"to": ["pka"], "content": {"text": ""}}, "reject_empty_semantic_publication")

INVALID = [
    ("publish", {"to": ["pka"]}, "empty_payload"),
    ("publish", {"to": ["pka"], "media": []}, "empty_media_only"),
    ("publish", {"to": [-100123], "content": TEXT}, "native_numeric_target"),
    ("publish", {"to": ["pka"], "content": TEXT, "platform": "vk"}, "unknown_field"),
    ("publish", {"to": ["pka"], "content": TEXT, "delivery": {"kind": "at"}}, "schedule_missing_time"),
    ("publish", {"to": ["pka"], "content": TEXT, "delivery": {"kind": "at", "at": "2026-09-06T12:00:00"}}, "offset_missing"),
    ("publish", {"to": ["pka"], "content": TEXT, "delivery": {"kind": "now", "at": AT["at"]}}, "irrelevant_field"),
    ("publish", {"to": ["pka"], "visual": {"kind": "tune", "brief": "Улучши"}}, "tune_missing_source"),
    ("publish", {"to": ["pka"], "media": [{"source": {"kind": "url", "url": "file:///etc/passwd"}}]}, "local_path"),
    ("publish", {"to": ["pka"], "content": {"text": "x", "paragraphs": []}}, "mixed_content_variants"),
    ("publication_update", {"publication_id": "pub_1", "change": {"kind": "delete"}}, "missing_cas"),
    ("publication_update", {"publication_id": "pub_1", "expected_revision": 1, "change": {"kind": "edit"}}, "empty_edit"),
    ("publication_update", {"publication_id": "pub_1", "expected_revision": 1, "change": {"kind": "reschedule", "delivery": {"kind": "now"}}}, "reschedule_not_now"),
    ("visual", {"command": {"kind": "generate", "brief": "x", "candidates": 5}}, "candidate_budget"),
    ("visual", {"command": {"kind": "select", "job_id": "visual_1", "candidate_id": "candidate_1", "expected_revision": 1}}, "selection_without_token"),
    ("visual", {"command": {"kind": "generate", "brief": "x", "allow_training": True}}, "model_cannot_grant_training"),
    ("engage", {"command": {"kind": "react", "item_ref": "item_1", "reaction": "👍"}}, "ambiguous_reaction"),
    ("destinations", {"command": {"kind": "set_put", "alias": "x", "label": "X", "members": ["pka"]}}, "set_missing_cas"),
    ("status", {"ids": ["op_1"], "retry": True}, "status_cannot_mutate"),
    ("read", {"query": {"kind": "raw_api", "method": "delete_all"}}, "no_raw_escape_hatch"),
]

if __name__ == "__main__":
    print(json.dumps({"version": "1.0.0-design", "jobs": JOBS,
        "invalid_calls": [{"tool": "vibepublish_" + t, "arguments": a, "reason": r}
                          for t, a, r in INVALID]}, ensure_ascii=False, indent=2))
