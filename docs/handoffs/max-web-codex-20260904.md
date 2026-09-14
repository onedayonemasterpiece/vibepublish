# Отдельная задача Codex: MAX Web adapter для VibePublish

Дата: 2026-09-04. Статус: готовая постановка; запуск Codex этим файлом не производится.
Repo: `onedayonemasterpiece/vibepublish`. Branch: `work/vibepublish-max-web-20260904` (существующую продолжить, иначе создать от актуального main).
Основное ядро разрабатывается отдельно по `docs/handoffs/implementation-start-20260904.md`.

## Цель

Реализовать специализированный MAX Web/Playwright adapter, который надёжно публикует и управляет **нативными отложенными MAX** и выдаёт промежуточные события в общий VibePublish ledger. Не писать ещё один сервис публикаций, общую MCP-поверхность, auth-систему или собственный планировщик.

MAX API не подключать и согласования API не ждать. Работа идёт с фактическим Web UI через один или несколько разрешённых persistent browser profiles. Не подменять сценарий общим агентом, который каждый раз заново придумывает клики.

## Маршрутизация исполнения

Одна bounded Codex task, а не независимые агенты на каждый этап. Для первичной диагностики использовать минимально достаточную реально доступную модель/effort; повышать только для реализации сложных переходов и отладки. Не назначать самый дорогой/high режим по умолчанию. Имена моделей и допустимость reasoning_effort сначала взять из текущего контракта Codex; не выдумывать параметры. Код и тесты сохраняются в этой ветке с точным SHA.

## Fresh-read и границы

Прочитать AGENTS.md, актуальный main/ветку и полный diff, затем social-operations README, implementation-design-v1.md, mcp-contract-v1.md, forwarding-and-editorial-profiles-v1.md, acceptance-tests-v1.md и текущий ProviderAdapter port, если core уже его создал.

Рабочие области: `adapters/max/`, `tests/adapters/max/`, `tests/browser/max/`, безопасные MAX fixture sources, MAX operations docs и отдельная конфигурация зависимостей адаптера. Общие domain/storage/MCP/HTTP schemas не переписывать. Если требуется изменение общего порта — сформулировать минимальную конкретную дельту и адаптироваться к согласованному интерфейсу, не создавать второй ledger.

Если ядра ещё нет, начать с чистого драйвера и локального fixture harness. Это не повод ждать или объявлять весь task blocked. Production wiring добавляется после появления общего port; такой harness не выдаётся за работающий MCP сервис.

## Граница с core

Адаптер получает только разрешённую immutable задачу: connection/profile reference, точный destination identity, operation/attempt ID, проверенный текст/entities, ordered asset manifest, native delivery time или now, ожидаемый remote item/fingerprint для изменения.

Методы общей границы: capability inspection, bounded prepare/read, execute native command, reconcile uncertain attempt. Конкретные Python типы определяет core в одном каноническом port. Никаких provider IDs/секретов в model-facing аргументах.

Core даёт awaitable callbacks:

- `emit_progress(stage, status, evidence)` — сохранить meaningful stage до продолжения;
- `checkpoint(transition, sanitized_state_ref)` — сохранить восстановимый переход;
- `before_effect(attempt_id, plan_digest)` — повторно проверить права/fence и durable dispatch marker, вернуть разрешение ровно на конкретное воздействие.

Финальная mutation выполняется только после успешного before_effect. При потере callback/DB-связи не кликать. После возможного клика — только observation/reconcile, никакого повторного submit по timeout или истечению lease. Callback сам по себе не решает гонку удалённого запроса: нужен отдельный profile/process lock и запрет takeover неоднозначного side effect.

## Функциональные сценарии

1. Проверка авторизованного аккаунта, точное открытие канала и различение одноимённых каналов.
2. Immediate text, text+single image, ordered multi-image, video — в реально поддерживаемых UI вариантах.
3. Native schedule: открыть соответствующий UI, установить время, подтвердить, затем прочитать **сохранённый элемент очереди** и проверить время/контент/медиа. Не считать composer или toast подтверждением.
4. Чтение всей доступной очереди канала с bounded pagination, включая записи других редакторов/клиентов, не только собственный ledger.
5. Edit/reschedule/cancel существующего scheduled item, delete опубликованного при поддержке и разрешении; прочитать результат там же. Не заменять reschedule удалением/созданием без отдельного решения.
6. Переподключение, DOM rerender, delayed media processing, process/browser crash и uncertain-outcome recovery.

Никаких delayed-send workers, cron/таймеров отправки, service scheduling fallback. Если реальный MAX UI/аккаунт/поверхность не поддерживает native schedule либо безопасный readback, вернуть доказанную capability limitation. Не заменять MAX API, немедленной публикацией или фальшивым локальным scheduled.

## Автомат состояний

CHECK_SESSION -> OPEN_EXACT_TARGET -> VERIFY_ACCOUNT_AND_TARGET -> OPEN_COMPOSER -> FILL_CONTENT -> UPLOAD_ORDERED_MEDIA -> VERIFY_COMPOSER -> SET_NATIVE_TIME_IF_REQUESTED -> BEFORE_EFFECT -> SUBMIT_ONCE -> OPEN_TARGET_QUEUE_OR_FEED -> LOCATE_EXACT_ITEM -> VERIFY_CONTENT_MEDIA_TIME -> RESULT.

После BEFORE_EFFECT любое падение потенциально неоднозначно. Повторный submit запрещён без доказательства отсутствия внешнего эффекта. Наличие старого одинакового поста не доказывает успех нового. Несколько кандидатов оставляют outcome_unknown. Смена target/account или потеря прав останавливает mutation.

Locators: role/label/accessibility/test-id где реально есть, scoped к уникальному контейнеру. Не использовать unchecked nth/координаты как нормальный путь. После rerender заново получать локаторы. Перед submit проверить readiness вложений и их порядок, текст/ссылки, аккаунт, destination identity и native time.

Предложенные bounds из design: до двух безопасных pre-submit восстановлений и ограниченный timeout попытки. После попытки — bounded observation/reconciliation, а не цикл публикации до успеха. Публиковать прогресс waiting_connection/uploading/submitting/reading_back/verifying независимо от Telegram/VK. Один заблокированный MAX profile не блокирует чужие provider lanes.

## Профили, безопасность и доказательства

Один профиль на provider connection, один владеющий процесс/side-effect lane на профиль. Отдельный OS user/ограниченные права, защищённое persistent хранение. Не запускать второй Chromium на тот же userDataDir. Не читать/экспортировать чужие браузерные профили.

Секреты, cookie storage, access tokens, QR/OTP и приватные посторонние чаты не попадают в Git, промпты или обычные логи. QR/CAPTCHA/OTP проходит только человек; не автоматизировать обход. Отсутствие login/test allowlist блокирует live writes, но не offline реализацию.

Партнёрский readback показывает разрешённый канал, не account-wide DOM. Cropped/redacted evidence хранить защищённо, с operation/destination, timestamp, driver version и hash. Зафиксировать реальные queue/item identity/permalink, если UI их даёт; иначе точную навигацию и доказательства, не выдумывать ссылки. Model-assisted recovery не делать до устойчивых детерминированных сценариев; она не получает право mutation.

## Автотесты

M01 wrong account -> zero clicks; M02 одинаковые имена каналов -> exact identity; M03 virtualized target/queue list; M04 rerender/stale dialogs до dispatch; M05 missing/reordered uploads; M06 delayed image/video processing; M07 session expired/QR; M08 crash до marker; M09 crash после submit; M10 одинаковые новые/старые посты; M11 concurrent profile claims; M12 schedule -> queue read -> edit/reschedule/cancel.

Использовать настоящий Playwright/Chromium на локальных sanitized fixture pages, включая контролируемые задержки/DOM замены, затем live canaries. Только mocked page object не считается browser proof. Тестировать desktop MAX UI; мобильный интерфейс здесь не требуется.

Ключевой интеграционный тест: real core MCP command на Telegram/VK/MAX с fake/fixture зависимостями; MAX задержан, но Telegram/VK события уже приходят в status. После искусственного crash post-submit восстановление той же operation без второго клика.

Live canaries — только в явно разрешённом owner test destination с безопасным fixture content. Проверить native schedule, остановить все VibePublish процессы до времени публикации и внешним наблюдателем подтвердить её исполнение MAX. Повторный старт не должен отправить ничего заново. Авторизация на эту тестовую запись должна быть задана при запуске задачи; не выбирать публичный канал самостоятельно.

## Definition of done и отчёт

Сохранить применимый adapter batch, тесты и minimal wiring без параллельного core. Отчёт: exact SHA/branch, окружение и Playwright/browser versions, пройденные offline/browser/live сценарии, ссылки/защищённые refs evidence, capability matrix (подтверждено/не поддерживается/не проверено), unresolved unknown operations и cleanup status тестовых постов.

Не писать «MAX готов» по исходникам или mock-тестам. Без live login/canary можно честно закончить offline implementation checkpoint и перечислить конкретные оставшиеся environment gates. Не запускать imagegen, не мигрировать EventsBot и не включать production publishing в этой задаче автоматически.
