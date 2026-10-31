# INC-2026-10-31 — полный asset после PR #118 недоступен текущему клиенту для imagegen

Status: `Open`  
Сквозная приёмка: `Not done`.  
Срез доказательств: **31 октября 2026, 16:23 UTC**; повтор пользовательского сценария — около **15:57 UTC**.  
Назначение: подробный handoff кодовому агенту владельца. **Только документация: исправление, deployment и публикация этим отчётом не выполняются.**

## 1. Краткий вывод

PR #118 исправил предыдущий этап: точное чтение отложенного VK-поста теперь создаёт asset с исходным изображением. В свежем ответе есть JPEG **327 936 байт** и immutable `vibepublish://assets/...` URI. Но текущий клиент dot не может получить **полные байты** по этому URI и передать их встроенному imagegen.

Уменьшенный preview работает. Он возвращает **768×563 WebP, 71 626 байт** — это не исходный JPEG. Использовать его вместо исходника или увеличить его разрешение не считается выполнением задачи.

На серверной стороне full-asset доступ уже реализован через MCP resource и авторизованный HTTP GET. Это подтверждено чтением актуального кода и серверным тестом PR #118. **Место расхождения в интеграции текущего клиента ещё не установлено.** Нельзя без дополнительного trace объявлять root cause ошибкой gateway, OAuth, MCP сервера или удаления asset.

### Состояния без двусмысленности

| Этап | Состояние |
|---|---|
| Найти точный отложенный пост | Успешно |
| Получить source projection после #118 | Успешно: asset + URI + MIME/size |
| Получить preview | Успешно, уменьшенный WebP |
| Получить полное изображение в текущем клиенте | Не удалось через доступные resource routes |
| Запустить imagegen от полного источника | Не выполнено |
| Обновить VK-пост | **Не вызывалось** |
| Неопределённый исход VK mutation | **Отсутствует: mutation не отправлялась** |
| Пост/расписание | Не изменены этим проходом |

Владелец ранее явно запретил браузер. Этот запрет остаётся в силе. Не нужны browser/cookies, подмена preview оригиналом или ручное извлечение credentials.

## 2. Цель и точный объект

Основное направление: `lovekenig_vk`, «Полюбить Калининград».

Текстовый ориентир: **«Карусели в парке имени М. Калинина»**, историческое фото Калининграда 1955–1960 годов. Полный ещё не опубликованный текст здесь не воспроизводится.

Плановая публикация: **2026-11-01 19:00 UTC / 21:00 Калининград**.

Итог исходного пользовательского сценария:

1. Встроенный imagegen клиента получает полное реальное фото выбранного поста.
2. Создаётся колоризация с компактной атрибуцией и CTA «Оригинал →».
3. Тот же postponed пост меняется на две фотографии: колоризация первой, прежний native original вторым.
4. Сохраняются исходный caption и расписание; абзац с просьбой писать о неточностях колоризации добавляется ровно один раз.
5. Не создаётся новый пост, не запускается publish-now, не меняется Telegram.

Текущий запрос владельца — **диагностический .md для своего кодового агента**, а не поручение автору отчёта выполнить эти записи.

## 3. Источники и границы достоверности

- **Observed / сообщено исполнявшим клиентом:** IDs свежих операций, возвращённые asset/preview metadata и ошибки маршрутов resources ниже.
- **Source-verified:** GitHub PR #118, актуальные `server.py`, `service.py`, соответствующий regression test в diff PR прочитаны при составлении отчёта.
- **Inference:** разрыв находится между получением серверного asset и доступным dot способом материализовать полный файл; конкретный слой пока не доказан.
- **Unknown:** активный deployment SHA, фактическая причина отсутствия resource forwarding у клиента, полный SHA-256 и размеры исходного JPEG в этом отчёте. Их нельзя придумывать по preview.

Репозиторий публичный. В документе нет токенов, private URL, cookies, email, Slack-пермалинков, приватных путей, полного base64 изображения и лишних персональных данных.

## 4. Свежие receipts и воспроизведение

### 4.1 Выбор и exact read

| Поле | Значение |
|---|---|
| Scheduled read operation | `op_72052a811ad44f8c908280cd22d7ba96` |
| Выбранный item_ref | `item_d9006459432746dcbce5bc7ae6679181` |
| Exact read operation | `op_ac5d600e4b16417cabca65eaf1cc20c2` |
| Exact outcome | `verified` |
| Source asset | `asset_3d591cdde008483488d7286ea1dd6d00` |
| MIME / размер | `image/jpeg`, **327936 bytes** |
| Resource URI | `vibepublish://assets/asset_3d591cdde008483488d7286ea1dd6d00` |

Безопасная read-only последовательность, по актуальному envelope `vibepublish_read`:

```json
{"query":{"kind":"scheduled","destination":"lovekenig_vk"}}
```

Выбрать именно нужное отложенное фото по времени/текстовому ориентиру. Затем:

```json
{"query":{"kind":"item","item_ref":"item_d9006459432746dcbce5bc7ae6679181"}}
```

В свежем exact результате source projection уже есть. `download_url` или full binary/blob для передачи во встроенный imagegen этот ответ не содержит. Item reference является scoped opaque ref, не публичным scheduled permalink.

### 4.2 Доступные resource routes

Исполнитель проверил:

1. `read_mcp_resource` с server `codex_apps` и точным asset URI:
   ```text
   -32002 Unknown resource
   ```
2. Попытка адресовать отдельный сервер `vibe_publish`: unknown server.
3. Resource templates в доступном текущему клиенту маршруте: пусто.
4. Resource listing: доступны plugin manifests, для VibePublish `mcp_servers=[]`.

Это **наблюдение текущего клиента**, а не доказательство отсутствия resource handlers в VibePublish. По коду они присутствуют (раздел 6).

Не требуется многократно повторять тот же несовместимый маршрут. Для дальнейшего теста нужен materially different доступный transport или подтверждённое исправление регистрации/экспонирования.

### 4.3 Preview работает, но не решает задачу

`vibepublish_asset_preview` для того же resource URI успешно вернул:

- `image/webp`;
- **768×563**;
- **71626 bytes**.

Preview пригоден для визуального осмотра и выбора источника. Его нельзя объявлять full source, автоматически подменять им JPEG 327936 bytes или делать upscale с утверждением, что исходник получен.

### 4.4 HTTP GET существует, но клиенту не предоставлен авторизованный перенос

`get_started` описывает `GET /v1/assets/{id}`. Авторизованный HTTP endpoint существует и в коде. Однако текущий клиент не имеет доступного установленного способа выполнить этот GET с корректной авторизацией и получить файл.

**Не делалось:** извлечение bearer/cookies из конфигураций, заимствование browser session, обращение к private URL в обход scopes, выдумывание download URL или публикация private asset наружу.

Проблема — не отсутствие знания URL-шаблона, а отсутствие доступного end-to-end transport с сохранением авторизации.

## 5. Что исправлено PR #118 — не чинить повторно

[PR #118](https://github.com/onedayonemasterpiece/vibepublish/pull/118) **merged 2026-10-31 13:53:44 UTC**.

- Head: `9d8f64c90abc9253f475bd87fc23a3b778a8a6ff`.
- Merge: `99b33808cfff1564cb118bd67e5c28974e08550f`.

По diff и описанию PR:
- Exact VK published/postponed read получает `orig_photo` либо largest rendition через существующий bounded transport.
- Создаётся `MediaDownload` и проверенное доказательство SHA/MIME/size.
- Используется прежний private single-asset `download_cache` с **одним часом** жизни, не новое permanent storage.
- Queue/feed остаются metadata-only.
- Original native attachment reuse и CAS не зависят от скачанных пикселей.
- Существует test реального SDK MCP resource + HTTP GET с full-resolution **1200×800** synthetic source.

Свежий live exact read с JPEG asset подтверждает, что прежний [source projection gap](INC-2026-10-31-vk-postponed-photo-source-preview-gap.md) в этом повторе больше не является текущим блокером. Не следует возвращать старый диагноз `media_projection_not_enabled` для этого verified exact результата.

Ранее PR #115 реализовал `existing.position=0` для сохранения исходного native photo при edit. Этот путь также не заменяет получение pixels на вход imagegen.

## 6. Проверенные file targets и существующая реализация

Следующие ориентиры прочитаны из текущего main при составлении отчёта. Номера строк могут сдвинуться; искать по функциям.

### `social_operations/server.py`

- `list_resource_templates`, строки **137–144**: для разрешённых scopes возвращает `vibepublish://assets/{asset_id}`.
- `read_resource`, строки **146–150**: вызывает `service.read_asset(actor(), asset_id)`, возвращает `ReadResourceContents(content=data, mime_type=mime)`.
- `asset_endpoint`, строки **233–239**: тот же `service.read_asset`, raw response с MIME, `Cache-Control: no-store`, `X-Content-SHA256`, `nosniff`.
- Route **255**: `GET /v1/assets/{id}`.

Ссылка на исходники: [server.py](../../../social_operations/server.py). Blob при чтении: `fae84f1a642cd39bc4be29479628e4e47e485ae4`.

### `social_operations/service.py`

- Asset preview branch, строки **70–74**: сначала `read_asset`, затем `render_asset_preview`.
- `read_asset`, строки **86–96**: purge cache, проверка текущего actor/scopes; выбор asset по **id + tenant_id + principal_id**; отсутствие возвращает `asset_not_available`.
- Дополнительные media-entry grants остаются в этом же пути.

Ссылка: [service.py](../../../social_operations/service.py). Blob при чтении: `6e4dc972bfd3ba96dc2137a0136e6fe83ad1454b`.

### Проверки и контракты

- `tests/runtime/test_transport.py::TransportTests::test_vk_exact_read_asset_is_full_resolution_in_mcp_and_http`: direct authenticated HTTP и direct MCP ClientSession получают точные synthetic bytes; проверяется full resolution и expiry.
- `tests/runtime/test_vk_native_carousel.py`: exact source, CAS, single-copy 1h cache, сохранение unfinished references, отсутствие соседнего item при missing scheduled ID.
- `contracts/social_mcp_v1.py`: актуальный tool catalog/output schema; проверить, какой file/binary результат реально проходит через текущий подключённый клиент.
- `docs/features/social-operations/vk-media-binding.md`, `docs/llm/vibepublish-social-skill.md`: ожидаемый dot-owned imagegen flow.
- Client/plugin registration / transport adaptation: **конкретный файл или владелец слоя пока не установлен**. Не придумывать имя gateway-модуля; получить trace на границе экспонирования прежде чем менять код.

**Ключевое различие тестов:** direct SDK server test доказывает серверный маршрут, но не реальную доступность этого маршрута через подключённый dot plugin. Требуется дополнительная клиентская интеграционная приёмка.

## 7. Гипотезы и минимальный план расследования

1. Сопоставить advertised capability VibePublish с фактически экспонированным tool/resource catalog текущего клиента. Проверить, поддерживается ли resource forwarding в этом типе подключения.
2. Найти, почему server-side template существует, а current-client template list пуст. Это может быть маршрутизация/экспонирование или ограничение конкретного client integration; пока не установленный root cause.
3. Проверить, может ли уже существующий asset pipeline возвращать клиенту supported file attachment / opaque file handle / безопасный краткоживущий download transport через **доступный MCP tool**. Предпочтительно переиспользовать `read_asset`, его auth и cache.
4. Если достаточно исправить регистрацию resources — доказать это реальным клиентом. Если resources в этой интеграции не поддерживаются — предоставить минимальный supported file-transfer surface, а не советовать недоступный вызов.
5. Не заставлять LLM переносить полный base64 через текстовое окно. Binary/file delivery должен материализоваться в файл, пригодный встроенному imagegen, без ручного переписывания bytes.
6. Явно связывать выдаваемый файл с immutable asset ID и source SHA-256, MIME/size; не смешивать preview SHA и source SHA.
7. Отдельно проверить expiry: cache живёт час. Старый 15:57 asset может истечь при поздней проверке; перед тестом получить свежий exact read. Истечение нового теста не считать повторением ошибки Unknown resource.
8. Если изменение нужно вне репозитория VibePublish — назвать точную границу и требуемого владельца компонента; не маскировать это новым хранилищем или обходом безопасности.

Нет основания добавлять вторую базу данных, постоянный original archive, фоновую очередь, новые генераторы или browser bridge. Нет основания повторно переписывать VK source downloader из #118.

## 8. Приёмка исправления

### A. Полные байты доступны именно текущему клиенту

- В том же подключённом dot-клиенте exact read отдаёт fresh asset ID, source SHA-256, MIME и size.
- Поддержанный tool/file-transfer маршрут доставляет **полный файл** в доступное imagegen место/attachment, не только URI, JSON или preview.
- Размер и SHA файла совпадают с immutable source evidence; MIME соответствует декодируемому файлу.
- Full-source dimensions считываются из файла. Не применять условие «обязательно больше 768» ко всем реальным фото; тестовый fixture >768 нужен, чтобы отличить full asset от preview.
- Для свежего текущего примера ожидаемый JPEG имеет 327936 bytes; при новом read проверять его собственный SHA/size, не вслепую требовать старый asset ID.
- Повторная доставка того же immutable asset не меняет bytes и не запускает генерацию/публикацию.

### B. Авторизация и негативные тесты

- Чужой tenant/principal и отсутствующий scope отклоняются.
- Отозванная авторизация не заменяется сохранённым токеном/обходным URL.
- Истёкший asset сообщает понятный refresh/asset-unavailable исход; fresh exact read восстанавливает новый короткоживущий источник.
- Сохраняется **1h download_cache** и защита references незавершённых операций; не увеличивать TTL до бесконечности ради удобства.
- Returned file/URL не раскрывает bearer, provider signed URL или access_key, не является постоянным публичным доступом к private asset.
- Если выбран краткоживущий URL, его scope/expiry и отсутствие credentials в логах проверены.
- Нет полного base64/pixels в текстовых receipts, логах или публичном Markdown.
- Preview и full delivery названы различно; tool не сообщает full успех при выдаче уменьшенного WebP.

### C. Сквозной клиентский сценарий после отдельного разрешённого исправления

1. Fresh exact item → полный файл текущему клиенту.
2. Этот файл → **встроенный imagegen dot**, не VibePublish visual generate и не восстановление из preview.
3. Результат → компактный JPEG примерно quality 90 → обычный verified import.
4. После импорта — новый exact item read, затем незамедлительный native edit:
   `[new imported asset, existing.position=0]`.
5. Тот же postponed post; **2026-11-01 19:00 UTC** сохранено; две фотографии в нужном порядке.
6. Caption и источник сохранены; абзац о неточностях ровно один.
7. Exact provider readback подтверждает schedule/text/ordered native attachments. Не трогать Telegram.
8. При uncertain write — reconcile original operation/request key, без повторного publish или нового ключа.

Никакие эти публикационные шаги **не выполняются при подготовке диагностики**. Если к моменту live acceptance срок уже прошёл, не выбирать publish-now автоматически.

## 9. Что не сделано и условия завершения расследования

- Браузер не использован.
- Credentials не извлекались.
- Preview не увеличивался и не выдавался за original.
- Imagegen от неполного источника не запускался.
- VK mutation не отправлялась; пост и расписание этим проходом не менялись.
- Runtime/deploy SHA отдельно не аттестован этим отчётом.
- Конкретная root cause в gateway/client/server boundary не установлена; кодовый агент должен подтвердить её трассировкой и минимальным regression test.

Достаточный результат: точное место разрыва, минимальное исправление или конкретная внешняя зависимость, проверка полного файла в **реальном текущем клиенте**, затем отдельно подтверждённая end-to-end приёмка. Одного direct SDK unit/integration test или сообщения «asset создан» теперь недостаточно.

## Resolution (заготовка для ревьюера — ещё не закрыто)

- **Кодовый путь, предлагаемый в PR:** `vibepublish_asset_preview(size="full")` возвращает `ImageContent` из прежнего авторизованного `read_asset` и те же байты в `structuredContent.full_data_url`; при размере >2 МиБ или длинной стороне >2560 px JPEG перекодируется с `reencoded:true`. Стандартные байты WebP-preview не меняются; первая текстовая часть ответа — чистый JSON для fallback Wonderful Lections, подсказка — отдельный TextContent.
- **После merge/deploy ревьюер фиксирует:** PR и SHA в `main`, фактический SHA запущенных API/worker, обновление схемы ChatGPT-плагина, живое получение источника dot через инструмент (а не MCP resource) и передачу именно этого ImageContent во встроенный imagegen.
- **Сквозная приёмка:** по свежему exact-read проверены исходник, корректная колоризация и native edit того же VK-поста с двумя фото по порядку, прежним временем и полным caption; приложены точные readback receipts. До этого инцидент остаётся `Open`, сквозная приёмка — `Not done`.
