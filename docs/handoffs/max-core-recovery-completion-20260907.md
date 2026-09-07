# Промпт для ChatGPT: завершить core recovery и разблокировать продолжение MAX PR #2

**Дата:** 2026-09-07. **Статус:** Not done / Not confirmed by user.
**Назначение:** единая точка передачи core-зависимости, не новая MAX-задача и не отчёт о готовом продукте.

**Уточнение после передачи:** владелец снял запрет на доработку ядра MAX-исполнителем.
Ниже сохранён checkpoint первоначальной передачи, а не действующий запрет на
core-работу. Новейший [отчёт core](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5573614571)
фиксирует новую реализацию и фактический safety-evaluation отказ её доставки;
remote `c4b1ff454bbc6592b4b5c62352a5a5ce7712110c` всё ещё содержит лишь документы.
В другом окне исходный ZIP уже найден; вручную переносить его повторно не нужно.
Это не разрешает обходить отказ другим writer/веткой/реализацией. Актуальное
MAX-продолжение — в [runbook](../operations/max-web.md).

---

## Задание принимающему окну ChatGPT

Продолжи существующую разработку VibePublish. Твоя роль — **core / PR #1**:
довести механизм восстановления неопределённой публикации до проверяемого,
доступного исполнителю результата. MAX-адаптер принадлежит существующему
Codex / PR #2. Не создавай вторую MAX-задачу, ветку или драйвер.

Пользователю нужен работающий MAX, а не обмен архивами и очередной отчёт о планах.
Результат этой core-задачи должен передаваться **ссылками на сохранённые документы,
код, commit и CI в GitHub**, без требования вручную переносить ZIP между окнами.
Сохраняй требования платформенной безопасности: это предпочтение доставки не
разрешает обходить ранее заблокированную операцию загрузки исходников.

Сначала прочитай этот документ и источники ниже, затем fresh-read актуальных
HEAD, diff, комментариев и CI обоих PR. Указанные SHA — проверенный checkpoint,
а не разрешение перезаписать более новые изменения.

## 1. Почему работа остановилась — простыми словами

1. При первом живом тесте MAX один помеченный пост **действительно появился**
   в «Тестовой группе». Ошибка исполнителя: отправка началась до готовности
   механизма подтверждения результата.
2. Браузер увидел пост и скопировал его точную native-ссылку, но приложение
   не смогло надёжно завершить исходную операцию. Ядро сохранило
   `outcome_unknown`: «эффект мог произойти, повторять нельзя».
3. Защитный файл профиля — quarantine/fuse — остался привязан к исходным
   `attempt_id` и `plan_digest`. Обычный рестарт старого worker не помогает:
   `outcome_unknown` уже terminal и не попадает в очередь незавершённых задач.
4. MAX read-only reconcile уже умеет повторно находить точный объект.
   **Наличие поста не равно доказанной связи с исходной отправкой**, а новое
   наблюдение не является автоматически разрешением удалить защитный файл.
5. Нужен core-путь: авторизованно наблюдать исходную операцию; либо доказанно
   разрешить её с сохранением истории и согласованным release, либо разрешить
   отдельную точную компенсационную очистку без фиктивного `verified`.
6. Автор core сообщил, что такой API реализован и протестирован **локально**,
   но исходники не доставлены в GitHub. На хосте MAX нового пакета нет.
   Поэтому правильная текущая формулировка: **не хватает доступной проверенной
   реализации для интеграции**, а не «никто ещё не написал recovery».

Пользователь разрешил сколько угодно тестов в тестовой группе. Недостатка
разрешения на эти социальные сценарии нет. Однако MAX-исполнителю отдельно
запрещено менять ядро/SQL, вручную снимать quarantine или обходить его новой
connection/profile. Количество разрешённых постов не устраняет эту техническую
и архитектурную зависимость.

**Не всё недоделанное объясняется core:** новый writer-to-MCP, production
атрибуция, edit/delete, media lifecycle и native scheduling в MAX тоже ещё
не завершены. Эта core-передача не выдаёт их за готовые и не снимает с MAX
исполнителя обязанность продолжить их после получения реального интерфейса.

## 2. Обязательные источники — читать в этом порядке

Все ссылки ниже ведут в репозиторий `onedayonemasterpiece/vibepublish`.

1. [PR #1 — существующая core-ветка](https://github.com/onedayonemasterpiece/vibepublish/pull/1).
2. [Исходный запрос core terminal-unknown recovery](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5551574373).
3. [Отчёт автора core: API реализован локально, доставка заблокирована](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5552197400).
4. [MAX → core: конкретный интерфейс наблюдения и границы](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5551880540).
5. [Уточнение владельца после неудачной отправки](https://github.com/onedayonemasterpiece/vibepublish/pull/2#issuecomment-5551577580).
6. [PR #2 — существующий MAX](https://github.com/onedayonemasterpiece/vibepublish/pull/2) и [последний подробный MAX-результат](https://github.com/onedayonemasterpiece/vibepublish/pull/2#issuecomment-5566046591).
7. [Канонический MAX runbook на проверенном SHA](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/docs/operations/max-web.md).
8. [Полная MAX-постановка L01–L16](https://github.com/onedayonemasterpiece/vibepublish/blob/1a650dc21c391ef9459e48a1a3b48b5013ce6a8f/docs/handoffs/max-web-live-completion-20260905.md).
9. [Implementation design, особенно раздел 8](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/docs/features/social-operations/implementation-design-v1.md).

Далее читай актуальные `docs/README.md`, `docs/routes.yml`, port, worker,
storage/application, контракт и tests именно **core-ветки**. MAX-ветка сохраняет
более старый contract snapshot; его нельзя ошибочно сделать новым core SoT.
Документы отдельного Imagegen/deployment rollout в PR #1 не расширяют разрешения
этой recovery-задачи.

## 3. Проверенные SHA и что действительно доступно

### Remote core

- Ветка: `work/vibepublish-core-20260904`, PR #1.
- Проверенный remote HEAD: `24c33d9e74efa6a28fa48ecb70287c60bca7ef5c`.
- [Дерево доступных исходников](https://github.com/onedayonemasterpiece/vibepublish/tree/24c33d9e74efa6a28fa48ecb70287c60bca7ef5c).
- Этот HEAD **не содержит** новую terminal recovery-реализацию из комментария
  5552197400. Не путай наличие текста отчёта с наличием runtime-кода.

### Локальная recovery-реализация, сообщённая автором core

Эти значения — provenance из core-комментария, **не remote commits**:

- LOCAL checkpoint: `564f76c0a5a4934fa1d37d4f6cea9e921670a1d9`.
- LOCAL tree: `618df472a50557523678abc5e8eb3cc47d90937a`.
- Изменено/добавлено 27 путей; cumulative patch относительно remote `24c33d9`.
- Patch SHA-256: `4e3212a563e9f923957c650e1f53beb69eeca34547fa2b5d983b67907b3580f4`.
- Port SHA-256: `308ea3d1c5a3aee1a5f8ccdf2053f14dbabe7347a30c5f6233fa17861676adc6`.
- Упомянутый ZIP: `vibepublish-core-recovery-20260905.zip`, 159087 байт,
  SHA-256 `a33fcd0654ba61fb774c1dbbeed6ae21d69761aad45c80685e9533106bcfc5cf`.
- На хосте MAX поиск по точному имени в `/home/dev`, `/tmp`, `/mnt`, `/var/tmp`
  не нашёл этот ZIP. Вложение старого окна ChatGPT не появляется автоматически
  в новом окне или на другом хосте.
- Нельзя ссылаться на эти LOCAL SHA как на доступный GitHub commit или потреблять
  упомянутое автором промежуточное unreferenced tree как готовую реализацию.

### Remote MAX

- Ветка: `work/vibepublish-max-web-20260904`, PR #2.
- HEAD: `45d084d1d0e528cd04bd9e3e18e5ed39a495c6af`.
- [RealMaxDriver](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/adapters/max/live.py).
- [MaxAdapter / RecoveryBinding](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/adapters/max/bridge.py).
- [ProfileLane / quarantine](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/adapters/max/profile.py).
- [Новые same-driver writer/restart тесты](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/tests/browser/max/observed/test_submit.py).
- [Существующие actual-port тесты](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/tests/browser/max/core/test_bridge.py).
- [Существующие реальные MCP ClientSession/worker тесты](https://github.com/onedayonemasterpiece/vibepublish/blob/45d084d1d0e528cd04bd9e3e18e5ed39a495c6af/tests/browser/max/core/test_transport.py).

## 4. Реальное состояние исходного поста и приватных данных

На 7 сентября заново прочитана исходная SQLite **read-only**: `outcome_unknown`,
ровно одна dispatched attempt. Quarantine совпадает с её attempt/digest.
Хэши ledger/quarantine не изменились за последнюю MAX-доработку.

Пост последний раз точно наблюдался live 5 сентября: правильный account/target,
исходная native-ссылка, outgoing, полное неизменённое содержимое и marker;
повторное независимое открытие и повторное копирование ссылки. 7 сентября
нового live-чтения не было. **Не сообщай о сегодняшнем наличии или удалении
без нового наблюдения.** Повторной отправки, правки и удаления не выполнялось.

Приватные факты намеренно НЕ лежат в публичном репозитории. Для будущего
локального MAX-исполнителя на исходном хосте уже сохранены:

- worktree `/home/dev/projects/vibepublish-max-web`;
- `artifacts/codex/max-publish-20260905/ledger.sqlite` — исходный business ledger;
- там же `publish-intent.json`, `publish-receipt.json`,
  `durable-before-effect.json`, `native-observed.json`, `exact-repeat.json`;
- `artifacts/codex/max-recovery-20260905/` — точные повторные наблюдения;
- `artifacts/codex/max-writer-20260907/` — последний read-only state audit и tests;
- существующий разрешённый профиль `/home/dev/.config/google-chrome-for-testing`.

Это навигационные пути, не инструкция запрашивать/публиковать их содержимое.
Не коммить телефон, native IDs/URLs, личный текст, credentials, cookies, токены,
SQLite или профиль. Для core-тестов используй вымышленные изолированные данные.
Не проси пользователя прикладывать авторизованный профиль или дамп ledger.
Локальный MAX-исполнитель сам сопоставит private identity при интеграции.

Старый полный core-архив на хосте MAX уже проверен: LOCAL HEAD
`870e2a4304c57ef5dd7152de63df1db6431a942b`, 103 source hashes;
port SHA `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
Он позволяет старые интеграционные тесты, но **не заменяет новую recovery delta**.
Подробности и существующий assembler — в MAX runbook.

## 5. Что именно требуется от core

Не придумывай ещё один несовместимый API по этому пересказу. Сначала проверь
локальную реализацию автора, если её реальные байты доступны в твоём окружении,
и актуальные source/contract docs. Ниже — обязательный acceptance contract.

### C01. Авторизованное observation-only восстановление

- Восстанавливать **исходную** terminal-unknown operation/attempt с её immutable
  request, plan digest и checkpoint, не запускать execute/Send повторно.
- Использовать текущую owner/binding/revocation проверку и fencing.
- Истёкший deadline первоначальной отправки не запрещает отдельно авторизованное
  ограниченное чтение, но не восстанавливает отозванные права.
- Сохранять отдельные durable observation/recovery events; не стирать старую
  историю и не сбрасывать idempotency/dispatched.
- Наблюдение MAX о существовании объекта должно оставаться `observed_only` /
  исходным `outcome_unknown`, пока нет достаточной атрибуции.

### C02. Доказанное разрешение и безопасный release

- Доказательство привязано к original attempt/digest/checkpoint/item/evidence.
  Проверять его содержательно, а не по наличию recipe name или hash.
- Сначала durable commit resolution, затем строго связанный release/ack профиля.
- DB failure, stale attempt, crash до/между commit и release не создают окна
  повторной отправки. Повтор release идемпотентен и не трогает чужой marker.
- Нельзя делать MAX-адаптер владельцем terminal state, core auth или dispatch.
- Конкретное имя сетевого WebSocket ACK не обязательно. Раздел 8 implementation
  design допускает защищённую точную UI-связку SUBMIT_ONCE → LOCATE → VERIFY.
  Но текст/последняя строка, пустой composer или успешный click сами по себе
  не доказывают causal receipt.

### C03. Точная компенсация, если атрибуция остаётся неизвестной

- Отдельный явно авторизованный и протестированный core-путь для **только
  наблюдённого исходного native object**, с актуальным fingerprint/readback.
- Не generic unlock, не force-success, не разрешение создавать новые посты.
- Повторный запрос/потеря ответа/crash после эффекта ведут к reconcile, не ко
  второму destructive effect. Чужой/заменённый/изменённый объект отклоняется.
- Честно сохранять исходный unknown и ограничения согласно canonical contract;
  не записывать задним числом, что первоначальная отправка была verified.

### C04. Согласовать настоящий port с существующим MAX

По отчёту core автора уже предусмотрены:

- RecoveryService, migration 4, команды `recovery.kind=inspect|compensate|release`;
- существующий MCP `vibepublish_publication_update`, без девятого инструмента;
- HTTP `POST /v1/recovery/commands`, тот же service и Idempotency-Key;
- additive `ProviderRequest.compensation`, `Observation.recovery_attribution`
  с default `None`, RecoveryAttribution / RecoveryRelease и
  `finalize_recovery(RecoveryRelease)`;
- provider capability `recovery_compensation_v1`, короткоживущий owner token и
  exact item/fingerprint/action binding.

**Это описание заявленной локальной реализации, не доказанный доступный API.**
Доставь и проверь настоящие типы/семантику, backward compatibility и migration.
Не заставляй MAX выводить типы из комментариев или писать имитационный port.
Существующий MAX RecoveryBinding возвращает actual-port
`Observation('outcome_unknown', items, missing_checks=...)`; prepare/execute
его live-ветки запрещены, quarantine не снимается. Нужен конкретный согласованный
способ подключения этого результата и будущей compensation-ветки, без дублирования
auth/ledger/idempotency/dispatch в MAX.

## 6. Обязательные проверки core и честные границы evidence

Для C01–C04 требуются executable tests, а не только документы:

- настоящий MCP ClientSession → application/service → worker → SQLite;
- original terminal-unknown inspect без повторного execute, включая expired
  original deadline, revoked owner/binding, stale fencing и concurrent commands;
- append-only persistence и сохранность исходной операции/частичных успехов;
- crash до/после observation, DB commit и release; replay release без Send;
- pending release одной операции не инвалидируется соседним inspect;
- точная compensation с token/fingerprint/action, denial чужого объекта;
- crash/response loss после compensation effect → reconcile без повторения;
- additive port совместим с существующими адаптерами;
- не ослаблять обязательные full-suite/CI gates ради зелёного результата.

Исторические числа автора core: 48 recovery tests прошли локально и повторно
из clean patch; диагностический прогон 344 + 199 subtests исключал missing
Imagegen test module; строгая collection завершалась ошибкой. Это не твои новые
результаты и не full green. Отдельную проблему `adapters/codex_imagegen.py`
не решать в рамках MAX recovery и не маскировать skip/stub.

Проверенные результаты MAX SHA `45d084d…`:

- original archived core + MAX: **164 passed, zero skips**;
- [remote CI](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/34090392917):
  **140 passed, 2 skipped отсутствующих core-модуля**, contracts 14 + 8;
- clean remote checkout: **26 новых writer qualification tests passed**;
- same RealMaxDriver loopback submit/ref/fresh read и настоящий post-submit
  process kill/restart, один simulated Send; live writer по-прежнему не включён.

Эти проверки НЕ доказывают новый recovery API, live compensation, полноценный
MCP writer или готовность L01–L16. Старые 37 fixture-тестов и реальная прежняя
MCP-интеграция с ранним TG/VK progress должны сохраниться после изменений.

## 7. Доставка без ручных архивов — и граница protection block

1. Работай в существующей core-ветке/PR #1, сохраняй чужие изменения и владение
   MAX PR #2. Никакого force-push, автоматического merge/deploy.
2. Когда нормальная доставка разрешена доступными инструментами, сохрани
   core-only законченную реализацию и документацию в GitHub; проверь remote SHA,
   фактические файлы и завершившийся CI. Успешный локальный commit не равен push.
3. В canonical core recovery-документе должны быть реальные signatures, migration,
   последовательность команд, output states, compensation/release protocol,
   тестовые команды и ссылка на неизменяемый source SHA. Дай MAX одно entrypoint
   `.md`, с которого доступен весь **проверенный runtime**, не только отчёт.
4. Если локальный checkpoint старого окна недоступен, явно сообщи, что восстановлен
   только контекст по ссылкам, а не его байты. Не выдавай вновь написанный код за
   исходный проверенный patch и не предполагай доступ к чужому sandbox.
5. В core-комментарии зарегистрирован safety-evaluation block при `create_tree`
   с port/storage. Не обходи его другой кодировкой, разбиением, другим инструментом,
   CI, MAX-веткой или передачей тому же действию другому агенту. Если блокировка
   сохраняется, зафиксируй точный текущий отказ и оставь delivery **Blocked**;
   запрос пользователя на GitHub-ссылки не отменяет этот запрет.
6. Не загружай полный старый core/архив через MAX PR. Не проси переносить файлы
   как будто их отсутствие — недостаток социальных разрешений пользователя.

**Прямой ответ на вопрос «всё ли уже в репозитории?» — нет.** В нём достаточно
постановки, MAX-кода и отчётных ссылок для понимания задачи. Новая core recovery
реализация по последней проверке в remote отсутствует; private live evidence
намеренно остаётся только на исходном хосте. Этот документ не исправляет
недоступность кода одним своим существованием.

## 8. Как передать результат обратно MAX-исполнителю

После реальной доставки/проверки core дай короткий ответ и обнови существующий
PR #1, не запускай новую MAX-задачу. В ответе нужны:

- один immutable GitHub URL на canonical recovery API/runbook;
- exact remote core SHA, port SHA, changed paths и фактический source readback;
- команды/counts, CI URL/conclusion; отдельно full/diagnostic/skip/blocked;
- конкретный delta для существующего MaxAdapter: inspect/reconcile,
  compensation capability, attribution (если доказуема), post-commit finalize;
- понятная последовательность для первоначального объекта, original operation и
  quarantine, с сохранением истории и без повторного Send;
- что остаётся MAX-работой и что ещё нельзя называть завершённым.

Следующий этап того же MAX-исполнителя: собрать дерево с **этим реальным core**,
добавить MAX-specific compensation/release integration и сквозные тесты,
восстановить/при необходимости точно очистить исходный пост; затем продолжить
publish → exact read → edit → delete и media/native scheduled L01–L16.
Никакой функции удаления по выдуманным селекторам или «успеха» по пустому экрану.

### Сохраняемые разрешения

- «Тестовая группа»: все необходимые социальные тесты, количество не ограничено.
  Не обходить текущий quarantine и core-owned resolution.
- «Ух ты, Калининград!» и **«Полюбить Калининград Анонсы»**: чтение и только
  собственные тестовые native scheduled в прежних границах — не immediate
  публичные тесты; точная cleanup до создания, максимум одна проба на канал,
  минимум 24 часа вперёд, очистка в том же прогоне. Сейчас созданных проб — 0.
- Существующая авторизованная сессия; без QR/login/logout/profile copying.
- Не использовать EventsBot credentials, прямой MAX API, imagegen, deployment,
  Telegram/VK/VisualService переписывание или обход protection block.

**Критерий завершения этой передачи:** core recovery реально доступен и проверен,
MAX получил точный executable interface по GitHub-ссылке либо честный конкретный
неустранённый delivery blocker. Сам документ/локальные тесты/вложение старого окна
не являются доставкой работающего core и не закрывают общую MAX-приёмку.
