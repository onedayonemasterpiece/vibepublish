# INC-2026-10-31 — после PR #119 текущий клиент всё ещё получает preview вместо full

Status: `Open`  
Сквозная приёмка текущим клиентом: `Not done`.  
Срез: **2026-10-31 17:44 UTC**, повтор сценария около **17:43 UTC**.  
Назначение: фактическая диагностика для кодового агента владельца. **Никаких исправлений кода, deployment или публикационных операций при составлении отчёта.**

## Summary

После сообщения владельца об обновлении сценарий повторён. Exact VK read успешно вернул исходный JPEG **1024×750, 327936 bytes**. `get_started` рекомендует `vibepublish_asset_preview(size:"full")`, но фактически доступная текущему клиенту декларация инструмента по-прежнему принимает **только `resource_uri`** и описывает только WebP preview.

По отчёту исполнителя, вызов с намерением передать `size:"full"` вернул обычный **768×563 WebP, 71626 bytes**, с `source_width=1024`, `source_height=750`, без `full_data_url` и `reencoded`.

**Доказано:** доступная клиенту декларация расходится с текущим GitHub-контрактом и инструкцией; результат соответствует preview, а не full.  
**Не доказано:** какой слой потерял/не принял `size`, дошёл ли этот аргумент до сервиса и на какой release был направлен конкретный вызов. «Gateway удалил size» — только гипотеза до trace.

Imagegen не запускался. Пост не изменён, mutation не отправлялась, uncertain VK write отсутствует. Браузер по-прежнему запрещён владельцем.

## 1. Точный объект и новые evidence

Направление: `lovekenig_vk`, основной «Полюбить Калининград».  
Пост: **«Карусели в парке имени М. Калинина»**.  
Прежнее время: **2026-11-01 19:00 UTC / 21:00 Калининград**.

| Поле | Новое значение |
|---|---|
| Exact read | `op_73fe391127864c539e8e50ff00dd9f73` |
| Exact result | `verified` |
| Source asset | `asset_5efd2932305c44b09f69797fdc031032` |
| URI | `vibepublish://assets/asset_5efd2932305c44b09f69797fdc031032` |
| Source | JPEG, 1024×750, 327936 bytes |
| Фактический ответ image tool | WebP, 768×563, 71626 bytes |
| Дополнительная preview metadata | `source_width=1024`, `source_height=750` |
| Full marker/transport | `full_data_url` отсутствует; `reencoded` отсутствует |

Не подставлять старые asset IDs из прежних отчётов. Cache временный; при позднем воспроизведении нужен новый exact read.

## 2. Проверенные границы фактов

- **Проверено автором отчёта:** GitHub PR #119 merged; main code/schema; фактическая декларация `vibepublish_asset_preview` в текущем tool catalog.
- **Наблюдал исполнитель:** свежий read/preview результат, данные выше и инструкция `get_started`.
- **Не проверено:** активные PID/release SHA, request body после connector normalization, серверные аргументы при входе `service.call`.
- **Не утверждается:** что full renderer сервера неисправен, что source JPEG утрачен или что изображение не было скачано из VK. Exact source уже успешно получен.

В публичный документ не включены токены, signed URL, private paths, Slack-пермалинки, полный base64 и приватный caption поста.

## 3. Реальная декларация текущего клиента

При discovery 17:43 UTC доступный инструмент:
`mcp__codex_apps__vibe_publish_vibepublish_asset_preview`.

Существенная часть фактически экспонированной сигнатуры:

```ts
args: { resource_uri: string; }
```

Описание: small metadata-free WebP preview; output schema содержит preview MIME `image/webp`, `preview_data_url?`, width/height, source/preview SHA, size_bytes.

В ней нет input `size`, full output `bytes`, `size:"full"`, `reencoded`, `full_data_url`. Это не реконструкция по старому отчёту: декларация прочитана заново при подготовке документа.

Инструкция `get_started`, напротив, предлагает `size:"full"`. Ответ preview уже содержит новые исходные dimensions. Такая комбинация совместима со stale client schema при обновлённом backend, но **сама по себе не доказывает**, что вся серверная цепочка обновлена.

## 4. Что реально merged в PR #119

[PR #119](https://github.com/onedayonemasterpiece/vibepublish/pull/119) — **merged 2026-10-31 17:30:24 UTC**.

- Head: `63e80fe6fac6cd5fbd2606eddfd5fb5c7b811526`.
- Merge: `79097810b8d60cabdd4e50c94ed9af9dc026be04`.
- В PR указаны full CI 6/6 на этом head и real SDK regression. Это свидетельство source/test delivery, не проверка текущего plugin-клиента.

### Main schema: `contracts/social_mcp_v1.py`

Строки **433–439**:
- optional input `size: "preview" | "full"`;
- только `resource_uri` обязателен;
- preview и full output альтернативы;
- full требует `resource_uri, source_sha256, mime_type, width, height, bytes, size, reencoded`;
- full может содержать `full_data_url`.

Full contract ограничен **2 MiB**, максимальная сторона **2560 px**. Если исходник помещается — точные original bytes, `reencoded:false`; иначе bounded JPEG с явным `reencoded:true`.

### Service: `social_operations/service.py`, строки 70–77

```python
data, mime, source_sha256 = self.read_asset(actor, ident)
if arguments.get('size', 'preview') == 'full':
    result = await asyncio.to_thread(
        render_asset_full, data, mime, source_sha256, resource_uri)
else:
    result = await asyncio.to_thread(
        render_asset_preview, data, source_sha256, resource_uri)
```

**Следствие из кода:** отсутствие `size` естественно выбирает preview. Но наблюдение preview не доказывает, кто именно и почему не передал `size`.

### Transport: `social_operations/server.py`, строки 109–127

- `metadata.get("size") == "full"` выбирает `full_data_url`, иначе `preview_data_url`.
- ImageContent и structured data URL строятся из одних bytes.
- Первый TextContent — чистый canonical JSON metadata.
- Preview hint о `size:"full"` идёт отдельным TextContent; full не получает preview hint.

Это важно для клиентов, отбрасывающих image block, и для JSON-only fallback. Нельзя исправлять проблему добавлением prose в первый JSON-блок.

### Ссылки для проверки

- [Contract](../../../contracts/social_mcp_v1.py)
- [Service](../../../social_operations/service.py)
- [Server](../../../social_operations/server.py)
- [Renderer](../../../social_operations/assets.py)
- `tests/runtime/test_transport.py::TransportTests::test_asset_preview_full_returns_original_or_bounded_jpeg_without_changing_default`

Проверенные blob IDs:
- contract: `8afddd420664a7cf467079067498850482addf70`;
- service: `88a7692adf9c263e5c9aba4946cdc4f2a7943835`;
- server: `379a3ef4e6ea1da44be8d18fa576654bd0347393`.

Строки относятся к main на момент чтения и могут сдвигаться.

## 5. Минимальное воспроизведение

В том же типе подключения и том же dot-клиенте, не только в direct MCP SDK test:

1. Получить fresh exact item read указанного postponed фото. Убедиться, что source JPEG имеет реальные width/height, MIME/size и asset ID.
2. Снять **фактическую client-visible schema** `asset_preview`, а не только schema из GitHub или server `list_tools`.
3. Сопоставить её с инструкцией `get_started`.
4. Если клиентский инструмент официально принимает optional `size`, запросить:
   ```json
   {
     "resource_uri": "vibepublish://assets/<fresh-asset-id>",
     "size": "full"
   }
   ```
   Это желаемый новый контракт, **не** утверждение, что текущая старая сигнатура его принимает.
5. Сохранить безопасный trace: какие аргументы отправил клиент; какие аргументы дошли до MCP/server и service; какой release обработал запрос; какую форму response получил клиент. Без image/base64 и credentials.
6. Проверить full markers и файл. Не принимать успешный HTTP/tool outcome за full-result, если это WebP preview.
7. Default и explicit preview должны по-прежнему давать preview и не ломать прежних потребителей.

В этом проходе факт: результат соответствует default preview. Request boundary trace пока отсутствует.

## 6. Гипотезы для проверки, не готовый диагноз

| Гипотеза | Как различить |
|---|---|
| Cached/stale plugin tool schema | Сравнить registered/exposed schema с фактическим server list_tools; проверить supported refresh/reconnect route |
| Аргумент отброшен normalization/validation | Safe argument trace на границах клиента и сервера; не гадать по ответу |
| Вызов направлен на старый runtime | Exact handling release/PID и schema того endpoint, не checkout HEAD |
| Wrapper использует старую input/output модель | Найти реальный generated tool wrapper / registration owner; не придумывать имя gateway файла |
| Full result отфильтрован response adapter | Сопоставить raw server metadata с client metadata, не публикуя binary |
| Реальный service regression | Только если `size=full` доказан на входе updated service, а renderer/response всё равно preview |

Сначала локализовать границу. Не добавлять ещё один image endpoint, cache, table, downloader или renderer пока существующий full branch не проверен через действующий клиент.

## 7. Приёмка

### Реальный текущий клиент

- Exposed input явно содержит optional `size` enum preview/full.
- Инструкция и tool schema согласованы.
- `size:"full"` действительно доходит до нужного service/runtime.
- Для **JPEG 1024×750, 327936 bytes** результат full должен сохранить исходные bytes (в пределах 2 MiB/2560), MIME JPEG, dimensions 1024×750, `bytes=327936`, `size="full"`, `reencoded=false`.
- `full_data_url` / ImageContent декодируются в одинаковые bytes с исходным SHA.
- Встроенный imagegen клиента может получить этот файл/attachment. Наличие URI/metadata без доступного изображения недостаточно.
- Default/preview возвращает прежний WebP; preview не называется full.
- Для oversized fixtures корректны bounded JPEG и `reencoded=true`; нельзя молча декларировать byte-exact source.
- Первый TextContent валидный JSON, без prose; structured fallback работает, если image blocks отсутствуют.

### Безопасность и regression

- Tenant/principal/scopes сохраняются через существующий `read_asset`.
- Чужой/expired asset не становится публичным благодаря full-mode.
- 1h cache и pending-reference protection не меняются ради обхода клиента.
- Нет токенов, подписанных приватных URLs и полного base64 в логах или LLM-тексте отчёта.
- Unsupported input не должен приводить к ложному сообщению «full доставлен».
- Negative tests должны отличать «parameter absent → preview» от «requested full → preview accidentally».
- Direct SDK CI обязателен, но не заменяет повтор в текущем connected client.

### Конечный сценарий — только после отдельного исправления/разрешённой приёмки

Full source → встроенный imagegen dot → compact JPEG import → **новый exact item read после импорта** → edit `[new asset, existing.position=0]` → verified provider readback.

Сохранить тот же postponed post, время **2026-11-01 19:00 UTC**, две фотографии в порядке colorized/original, исходный caption с одним абзацем про неточности. Не трогать Telegram; не публиковать немедленно и не создавать дубликат. Если ответ mutation uncertain — reconcile исходный request/operation, не новый send.

## 8. Связь с прежними отчётами

- [Source projection gap](INC-2026-10-31-vk-postponed-photo-source-preview-gap.md) решён для этого сценария PR #118: exact read уже возвращает источник.
- [Full asset transport after #118](INC-2026-10-31-full-asset-client-transport-after-pr118.md) описывал недоступный MCP resource/HTTP transfer в текущем клиенте.
- PR #119 добавил tool full mode вместо зависимости только от resource route. **Нынешний новый симптом — exposed schema и фактический ответ ещё не соответствуют full контракту.**

Не откатывать #118 и не повторять работу native original reuse. Не закрывать инцидент только по merge #119.

## 9. Что не сделано

Браузер не использован. Preview не увеличен и не отправлен как original в imagegen. Imagegen, import результата и VK edit не выполнялись. Пост/время неизменны; uncertain publication нет. Runtime не перезапускался, код не менялся.

Ожидаемый результат кодового расследования: назвать точную границу расхождения, минимально исправить её и предъявить successful full consumption **тем же текущим клиентом**, а не только новый green server test.

## 10. Follow-up — 2026-10-31 17:52 UTC: ручной Refresh tools не изменил текущий каталог

По сообщению владельца, **17:51 UTC** выполнен ручной Refresh tools. После этого root и исполнитель независимо перечитали `ALL_TOOLS` около **17:52 UTC**.

Оба увидели прежнюю декларацию:
- input `args: { resource_uri: string; }`;
- описание `small metadata-free WebP`;
- output MIME `image/webp`, `preview_data_url`;
- параметр `size` и full-result поля отсутствуют.

**Наблюдение:** ручное обновление не отразилось в каталоге, доступном этим текущим сессиям на указанное время. **Не установленная причина:** cache, scope refresh, registration propagation, wrapper или иной слой. Без trace нельзя объявлять, что refresh вообще не выполнился или что connector удаляет аргумент.

Новый asset call после Refresh **не повторяли**. Генерация, импорт результата и VK mutation не выполнялись; прежний пост/время остаются без изменений.

### Уточнённый журнал предшествующей попытки 17:43

Исполнитель дополнительно предоставил metadata без binary:
- 17:42:34: scheduled read `op_cb3b485d67504fafbba8992c15722497`, verified; item `item_6c26ac1a996e404c9483e500c09e8719`.
- 17:42:57.656: exact read `op_73fe391127864c539e8e50ff00dd9f73`, verified; observed 17:42:59.340, fresh item `item_8ca5708c8d544f0ca0259f08f89fce1a`.
- Source SHA-256: `5a96db2654b177862704f788509c08da67a35b1cf59124e2ea42239be3c58794`.
- 17:43:06–17:43:12: JavaScript call передавал `{resource_uri:"vibepublish://assets/asset_5efd2932305c44b09f69797fdc031032",size:"full"}`; это аргументы на стороне вызывающего кода, **не wire trace сервера**.
- Ответ `isError:false`; source SHA совпадает, preview SHA `bb3fcfd21d37130a8671c5dff34ca63921e86ce2aaeae30cda719e0c6ea24a7f`.
- Preview WebP 768×563 / 71626 bytes, исходные dimensions 1024×750; присутствует `preview_data_url`, затем ImageContent `image/webp`.
- Текстовый hint предлагает запросить `size:"full"`. Поля `full_data_url`, `size`, `reencoded`, `bytes` отсутствуют.

Таким образом, конкретный вызывающий код включал full-параметр, но серверные входные аргументы всё ещё не наблюдались. Гипотеза потери аргумента остаётся гипотезой.
