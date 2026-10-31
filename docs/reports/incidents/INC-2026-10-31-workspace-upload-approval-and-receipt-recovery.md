# INC-2026-10-31 — прерванный workspace upload: approval-review failure и утраченный receipt

Status: `Open` — upload recovery подтверждён; сквозная публикационная приёмка отдельна  
Назначение: диагностический handoff кодовому агенту владельца. Срез: **2026-10-31 18:36 UTC**.  
**Только документ.** Автор отчёта не загружал bytes, не завершал/отменял upload, не редактировал посты, код или runtime.

## 1. Summary

В задаче колоризации следующих десяти отложенных VK-фотопостов **2–11 ноября** пост **2 ноября** уже обновлён и подтверждён readback. Для поста **3 ноября** успешен `import_begin`, затем попытка `import_chunk` остановлена до выполнения на уровне автоматической проверки разрешения.

Сообщение инструмента:

```text
Automatic approval review failed: authorization changed before approval could be applied.
The action was not executed.
```

Дополнительный смысл сообщения: это review failure, а не заключение о небезопасности действия; не обходить отказ.

**Это не полученный VibePublish API error и не доказанный отказ VK.** Вместе с тем проблема не сводится к фразе «просто разрешение»: агент не сохранил returned upload_id/receipt вне локальной переменной завершившегося isolate. Поэтому текущий partial-upload state нельзя восстановить из памяти и нельзя выдавать за завершённый/отменённый.

`import_finish` и edit поста 3 ноября **не вызывались**. Пост не изменён. Неопределённой VK-записи нет.

## 2. Три независимых слоя

| Слой | Наблюдение | Чего это не доказывает |
|---|---|---|
| Approval review | Chunk action explicitly not executed из-за изменения authorization до применения approval | Не доказывает runtime/API bug и не даёт права обходить gate |
| Агент/orchestration | Receipt/upload_id остался только в локальной переменной isolate и не сохранён | Не доказывает потерю серверной записи |
| Vibe workspace upload | Begin успешен; текущее состояние требует reconciliation | Нельзя объявить upload complete, aborted, expired или 0 bytes без статуса |

Fresh разрешение владельца 18:33 на действия, если причина только в разрешении, — новый контекст полномочий, но оно не меняет задним числом результат chunk и не восстанавливает пропавший receipt. Перед продолжением надо установить исходный upload и неизменность intent.

## 3. Изменение требования после начала загрузки

В **18:29 UTC** владелец уточнил оформление:
- префикс **«Источник:»** обязателен;
- **«Оригинал →»** должен быть заметным.

Исполнитель подготовил исправленный JPEG. Старый JPEG теперь не соответствует актуальному требованию.

Это важно для безопасного восстановления: upload session фиксирует `source_sha256`, MIME и byte length в begin. **Нельзя отправлять bytes исправленного изображения в upload старого изображения** или переиспользовать старый request_key с изменённым intent. Такое продолжение должно конфликтовать или провалить integrity, а не «догрузить как получится».

Отдельная session/новые keys для действительно нового файла допустимы только как новая версия контента после reconciliation прежнего upload и проверки актуального разрешения, не как обход denied/unknown action.

## 4. Проверенный контракт и код

Прочитаны:
- [Asset ingress](../../operations/asset-ingress.md);
- [Workspace ingress](../../../social_operations/workspace_asset_ingress.py), blob `e48aa9ad7ba90bfccfe90889b56d4dcf4e399fa6`;
- [Service status](../../../social_operations/service.py);
- [MCP contract](../../../contracts/social_mcp_v1.py).

### Begin/chunk/finish

В `workspace_asset_ingress.py`:

- `_validate`: begin включает **source_sha256 + mime + size_bytes**. Chunk включает **upload_id + offset + canonical data_base64**; в ledger сохраняются hash/size chunk, не raw base64.
- Каждый command имеет стабильный `request_key`.
- `service._replay(... implicit=False)` возвращает исходную операцию при том же key и intent.
- Максимум chunk **196608 decoded bytes / 262144 base64 chars**.
- `_owned` связывает upload с **tenant_id, principal_id, actor_epoch**.
- `import_chunk`: append только на текущем offset. Повтор уже полученного диапазона принимается только при совпадающих bytes; иначе `workspace_upload_offset_conflict`.
- `_finish`: требует complete length и matching full SHA; иначе `workspace_upload_incomplete` / `workspace_upload_integrity`.
- Terminal completed upload содержит `resource_id`; только после verified finish есть asset для edit.
- Upload TTL **3600 секунд**, максимум **2 receiving sessions** на principal; очищение staging уже существует.

Ни import_begin, ни chunk сами не публикуют пост.

### Read-only recovery сначала

`Application.status` читает текущего actor и receipts:

- с `ids` — указанные операции;
- без `ids` — последние операции **текущего tenant/principal**, до заданного limit;
- не выполняет send/write, не запускает upload заново.

Это первый существующий read-only способ найти recent begin receipt, если operation/upload ID не сохранён. Результат нужно сопоставить с точным action/intent/hash/size/key и временем, а не выбрать просто ближайший upload.

**Не все вызовы со словом status полностью read-only.** `vibepublish_visual(command.kind="import_status")` требует `upload_id`; реализация запускает expiry cleanup и создаёт durable operation/key receipt через `_record`. Он не передаёт chunks и не публикует пост, но это не то же самое, что чистое `vibepublish_status`.

Повтор **того же** import_begin с точным ключом и аргументами реализован как replay. Это recovery-механизм, однако не нужно начинать с повторной write-shaped команды после отказа, если можно сначала прочитать сохранённые receipts.

### Идентификаторы не угадывать

Утраченный upload_id нельзя придумать, вывести из source asset_id или заменить новым «чтобы пошло». Отсутствие у агента receipt не равно отсутствию операции на сервере.

Если actor epoch изменился, `_owned` может не дать доступ к прежней session. Это следует показать как конкретный auth/state result; нельзя менять epoch/ACL или выполнять чужой upload для обхода.

## 5. Минимальный безопасный план расследования

1. Сохранить exact approval error и границу выполнения: какая команда точно не исполнилась.
2. Через обычный read-only `vibepublish_status` найти begin operation в последних receipts текущего principal. Не отправлять chunks в ходе диагностики.
3. Зафиксировать recovered operation_id/upload_id, frozen SHA/MIME/size, received_bytes, state, expiry и timestamp результата. Секреты/base64 не включать.
4. Сопоставить с локальным старым и исправленным JPEG: hashes/length отличаются или нет. Изменение видимой подписи обычно меняет bytes; не полагаться на имя файла.
5. При необходимости использовать документированный exact status под действующей авторизацией; не превращать неизвестный state в новый upload автоматически.
6. Разделить результат:
   - denied chunk действительно not executed;
   - begin создан;
   - ранее принятые chunks, если были, перечислены по receipt;
   - finish/edit не вызваны.
7. Если понадобится продолжение, сначала определить судьбу старой версии и правильный intent исправленной версии. Не переносить старые keys на новый SHA.
8. Fresh разрешение проверять обычным путём. Если повторное разрешение опять не применяется — остановить зависимую запись с точным блокером, не менять канал/инструмент для обхода.

Диагноз approval subsystem требует его собственного trace. Source-reading VibePublish не даёт доказательства того, почему external authorization менялась.

## 6. Улучшение orchestration — не новый продуктовый механизм

Доказанный риск: данные begin жили только в scope одного JS isolate. Следующий tool call / failure не должен уничтожать единственный путь reconciliation.

Минимальная дисциплина:
- сохранять bounded receipt и upload_id сразу после begin, **до** chunk;
- manifest содержит content SHA/size/MIME, version label, request keys, offsets и outcome;
- писать actual outcome после каждого шага;
- не хранить tokens/raw base64;
- при failure читать существующий state, не перезапускать публикацию;
- при новой редакции файла фиксировать новый SHA и не смешивать версии.

Это не основание добавлять VibePublish новую DB, queue, неограниченный retry или дополнительный publish worker. В коде уже есть ledger/status/idempotency.

## 7. Приёмка расследования и негативные проверки

### Для этого инцидента

- Найден исходный begin receipt либо честно указано, какой read-only route не смог его получить и почему.
- Текущее receiving/completed/aborted/expired state подтверждено инструментом, а не догадкой.
- Отдельно доказано, что chunk с review failure не был выполнен.
- Исправленный JPEG соответствует «Источник:» и заметному CTA; старые bytes не могут попасть в новый итог.
- До verified finish не объявлять asset imported.
- До fresh edit + exact native readback не объявлять пост изменённым.
- Пост 2 ноября не дублировать; 3 ноября и последующие обрабатывать только согласно их фактическим receipts.
- Плановые даты/время и native originals сохраняются; Telegram не затрагивать.

### Negative cases

- Same key + same begin intent возвращает original receipt, без второй session.
- Same key + changed SHA/size/MIME конфликтует.
- Same offset + different bytes отклоняется.
- Partial upload не проходит finish.
- Истёкшая session не возрождается обходом deadline.
- Чужой principal/tenant/epoch не получает staging.
- Agent process/isolate failure после begin не теряет возможность reconciliation из durable receipt.
- Approval rejection не маскируется как API failure, и наоборот.
- New authorization не служит разрешением повторять uncertain provider mutations.

## 8. Область незавершённости

Этот отчёт не считает утверждение «проблема только в разрешении» доказанным. Доказан технический отказ approval review; дополнительно установлен agent-side receipt persistence gap. Состояние конкретного upload требует отдельного readback.

Не выполнялись автором документа: import/chunk/finish/abort, смена прав/epoch, VK edit, code fix/deploy. Полный batch из десяти постов не объявляется завершённым.

## 9. Полученные точные evidence — 18:35 UTC

Исполнитель подтвердил время отказа около **18:29:41 UTC** и полный текст:

```text
Automatic approval review failed: authorization changed before approval could be applied
The action was not executed because automatic approval review could not be completed.
This is a review failure, not a determination that the action is unsafe.
Do not bypass the approval check; resolve the error or ask the user for guidance.
```

- Команда: `vibepublish_visual`, `command.kind=import_chunk`, файл старой редакции для поста **03.11**.
- Успешный begin key: `colorize-ten-20261031-02-begin`.
- Шаблон chunk key: `colorize-ten-20261031-02-chunk-{offset}`.
- **Точные upload_id, operation_id begin и offset отказавшего chunk не сохранены** в завершившемся isolate. Не утверждается, что отказ был обязательно на первом chunk.
- Finish и edit не запускались; цикл прервался.
- Поиск recent receipts пока не дал сообщённого исполнителем результата. Старые chunks повторно не отправлялись.

### Byte identity двух версий: проверено локально read-only

| Версия | Bytes | SHA-256 |
|---|---:|---|
| Старая, привязанная к begin | 562145 | `dfe99dfa1066fe9ce835608471d4fb8354b69a317595b3336d6d8a9853630c79` |
| Исправленная после требований к подписям | 483367 | `ebd3604bdf174eb1081293813b4502bbd1444984c38fa1b4d750b751fd4d65bd` |

Измерены реальные файлы; приватные локальные пути не публикуются. **Различие SHA и длины подтверждено**, это не только предположение о новом оформлении. Старый upload нельзя завершать исправленными bytes.

### Уже выполненный пост 02.11 — не дублировать

- Edit operation: `op_4ee408d1c1d04558963b2dfd1793a818`.
- Verified readback: `op_c4b04bbe60404241a9aa492f1ca06cee`.
- По отчёту исполнителя, оригинал сохранён вторым; его evidence SHA:
  `8945430717ca50cabb7915a76b5c84669e388942132c0ee9d76313e4baabbbd8`.

Эти receipts относятся к **02.11**, а остановившаяся загрузка — к **03.11**. Не переносить успешный результат первого поста на второй или на весь batch.

## 10. Recovery checkpoint — 2026-10-31 18:43 UTC

Предыдущие неизвестные относятся к историческому срезу. **Исходный upload найден read-only, штатно отменён; исправленная версия успешно импортирована.** Это не отменяет зафиксированную ошибку approval review, но снимает неопределённость staging. Дополнительных изменений кода или серверного механизма для recovery не потребовалось.

### Read-only восстановление receipt

В **18:36:53 UTC** исполнитель выполнил `vibepublish_status({limit:30})`:

- Upload: `upload_04ff5d8ec4d34f0f8cc7f4b304f0680b`.
- Begin: `op_a52e2a6f04c445f99d5a82a4735bde91`, **18:28:10.577358 UTC**.
- Первый принятый chunk: `op_b2cb09d9e7c747da9bd7ec694b0264f6`, **18:28:33.779499 UTC**; received **196608**.
- Второй принятый chunk: `op_d77f10d1aabc4cceb91efb1bb7a4a054`, **18:28:58.692073 UTC**; received **393216 / 562145 bytes**.
- Состояние на этом receipt: `receiving`; expiry **19:28:10.416603 UTC**.

Offset отказавшего chunk **393216**, key `colorize-ten-20261031-02-chunk-393216` восстановлены **по принятым receipts и последовательному шагу цикла**, а не из несуществующего service receipt отказанного действия. Finish и edit до отказа не выполнялись.

### Завершение старой версии и импорт новой

После нового разрешения владельца и координации исполнитель применил обычный `import_abort` к устаревшему upload:
- **18:37:36.292997 UTC**, `op_c42e4136ee8b4196abfc89eae4c69e15`;
- `aborted` дополнительно подтверждён отдельным status;
- старый denied chunk **не повторялся**.

Исправленный JPEG импортирован как новый content intent с собственными keys:
- новый upload `upload_6d22ee7a216546f99897f193c43cccd0`;
- verified finish **18:39:20.407133 UTC**;
- operation `op_5046a56fdfde4f9ebf95f8dfe7da87a8`;
- asset `asset_b9740102c5124e7984519141db1d8ee9`;
- **483367 bytes**, source SHA-256 `ebd3604bdf174eb1081293813b4502bbd1444984c38fa1b4d750b751fd4d65bd`.

Это новая редакция изображения с другим SHA, не обход отказа повторной отправкой старого chunk. Receipts сохранены исполнителем по шагам; приватные пути не публикуются.

**PASS только upload recovery:** найден прежний state, старая версия закрыта штатно, новая версия имеет verified asset. Из этого не следует, что весь batch 02–11 ноября завершён. Edit/readback поста 03.11 выполняется отдельно; до его подтверждения не считать пост обновлённым.
