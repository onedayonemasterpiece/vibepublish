# Новое окно ChatGPT: начать реализацию VibePublish

Дата: 2026-09-04. Статус: постановка разработки, не отчёт о работающем сервисе.
Репозиторий: `onedayonemasterpiece/vibepublish`.
Контракт: `1.2.0-design`, `contracts/social_mcp_v1.py`.
Исторический checkpoint до последних дополнений: `7d55d4718c74720bde411b2838b7d59272fd8816`. Перед работой разреши актуальный main; этот SHA не замораживает базу.

## Задача

Работай самостоятельно в этом окне через GitHub. Начни реальную реализацию, а не очередной полный аудит или перепроектирование. Не делегируй ядро, Telegram/VK и MCP в Codex/другим агентам. MAX Web разрабатывается отдельной задачей по `docs/handoffs/max-web-codex-20260904.md`; не дублируй её драйвер.

Создай или продолжи одну ветку `work/vibepublish-core-20260904` от актуального main. Сначала проверь, нет ли уже этой ветки и полезной реализации; не затри её и не создавай второй runtime. Работай последовательными применимыми code batches, сохраняя прогресс в GitHub. Документационные статусы не выдавай за реализацию.

## Fresh-read

Прочитай AGENTS.md, README.md, docs/README.md, docs/routes.yml, затем:

1. `docs/features/social-operations/README.md`;
2. `docs/features/social-operations/implementation-design-v1.md`;
3. `docs/features/social-operations/mcp-contract-v1.md`;
4. `docs/features/social-operations/forwarding-and-editorial-profiles-v1.md` — последняя обязательная дельта;
5. `docs/features/social-operations/acceptance-tests-v1.md`;
6. `contracts/social_mcp_v1.py`, `contracts/task_corpus_v1.py`, оба файла `tests/contracts/test_*.py`;
7. `docs/llm/vibepublish-social-skill.md`, social-visuals/README.md и donor map;
8. отдельную MAX-постановку — для общей границы адаптера, не для повторной реализации MAX.

В events-bot-new разреши актуальный main и прочитай реальные Telegram/VK donors и их тесты из donor map. Не импортируй EventsBot как runtime-зависимость и не используй его credentials. Исторические аудит/handoff не отменяют поздние поправки владельца.

## Неизменяемые требования

- Telegram, VK, MAX Web. MAX API не нужен.
- **Нет собственного планировщика публикаций.** Команда сейчас создаёт нативное отложенное у провайдера; исполнение в будущем принадлежит провайдеру. При отсутствии возможности — явная ошибка, не локальный таймер и не немедленная публикация.
- Edit/reschedule/cancel идут к существующему remote item и проверяются там. Отмена не равна локальному флагу или удалению уже вышедшего поста.
- Сразу durable accepted receipt, затем атомарные этапы и результаты каждого назначения. Медленный MAX не скрывает готовый Telegram. `status` с event cursor возвращает первое новое событие, не ждёт всех провайдеров. Polling не создаёт новую публикацию.
- Партнёр читает всё в своих действующих каналах публикации, включая отложенные других редакторов; не читает остальные каналы/диалоги. Владелец читает всё реально доступное его подключению. Source lookup для конкретного публичного форварда не превращается в общий read grant; приватный operator-only источник не раскрывается партнёру по одной ссылке.
- История/статистика — индекс фактов в БД с remote IDs и observed_at, не очередь исполнения. История не выдаётся за актуальные отложенные.
- Нативные Telegram forward и VK wall repost по item_ref или ссылке, с сохранением источника. Не переписывать/копировать вместо пересылки и не обходить защиту. Межплатформенную копию нельзя называть нативным форвардом. Scheduled VK repost требует отдельного доказательства native capability.
- Сохранённые назначения/наборы имеют purpose, notes, primary/secondary и разрешённость выбора агентом. Модель может выбрать явно подходящий разрешённый канал для поставленной пользователем задачи; неоднозначность не решается публикацией во все каналы.
- Готовый skill отдаёт существующий `vibepublish_get_started`, включая forwarding/destinations sections и динамические profiles. Не добавляй дублирующий девятый метод.
- Свои подключения пользователей и operator-shared точные bindings; tenant isolation с первого кода. Права, секреты, media handles, candidate selection и cursor scope проверяются сервером, а не доверием к модели.
- `$imagegen` через заданный ранее маршрут — отдельный executor. В этом окне реализуй его интерфейс/fake и интеграцию с visual service; live маршрут проверяется отдельно. Не подменяй Google Imagen и не запускай imagegen ради реализации.

## Реализация по стадиям — начать с первой сейчас

### A. Исполняемый сквозной core

Материализуй пакет, зависимости/lockfile, SQLite migrations/repositories, principals/bindings/профили, immutable request/plan revisions, assets, durable operations/attempts/progress journal и command worker. Не держи транзакцию во время внешнего I/O. Очередь текущих команд/наблюдений не должна содержать таймер отправки в requested_at.

Сразу зафиксируй общий ProviderAdapter port и fake implementation. Граница с MAX из отдельной постановки: prepare/read/execute/reconcile, immutable scoped request, awaitable progress/checkpoint hook, before_effect guard. Ядро единолично владеет auth, ledger, idempotency и durable dispatch marker; адаптер — реальным провайдером. MAX-драйвер не пишет свою бизнес-БД. Передай точный путь/commit этого порта в рабочий отчёт, чтобы отдельная задача могла интегрироваться без дублирования.

Сделай настоящий MCP/HTTP server поверх одних application services и minimal owner CLI для тестовых principals/bindings. Тестовый E2E должен через реальный MCP client создать публикацию, увидеть accepted и раздельный прогресс fake Telegram/VK/MAX, перезапустить worker и прочитать сохранённый результат. Не ограничивайся dataclasses и CRUD без вызова через интерфейс.

### B. Telegram/VK и редакционные задачи

Перенеси reusable adapters/upload/readback и regression behavior из actual donor source, с provenance. Реализуй immediate/native scheduled posts, ordered media, queue reads, edit/reschedule/cancel/delete и нативные forward/repost. Раздели реальные account types/capabilities. Добавь metadata profiles, bounded bootstrap, history/metrics и source-access security tests. Не объявляй capability supported по одному наличию SDK-функции.

### C. Visual integration и полный контракт

Один VisualService для inline/standalone generation/tune/compose/select; immutable lineage, compositor contract, выбранный asset hash, approval/CAS и fake executor. Проверь все восемь методов и scoped variants на соответствие canonical schema. Неподключённый MAX возвращает needs_auth/needs_review, а не выдуманный успех. Не урезай навсегда stories/rich media/read/analytics donor baseline; оставшиеся capability gates перечисли точно.

## Автотесты и CI

Начальный реальный результат дизайна: 22 unittest methods, 16 schemas, 125 golden/44 negative calls. Запусти их заново; это не runtime tests.

Реализуй тесты из acceptance-tests-v1.md по мере каждого code batch: real SQLite concurrency и process restart, dispatch uncertainty, fan-out partial results, progress timing, scoped read/cache/assets, native queues, forward attribution/source rights, profile CAS, routing freshness, history/metrics и MCP/HTTP parity. Не выдавай строки runtime_oracle за исполненные проверки.

Один GitHub-hosted CI workflow: contract + unit + integration с fake providers. Никаких self-hosted runners и live social writes в PR CI. Локальная сеть или SDK недоступны — используй доступный GitHub workflow для честного прогона, не объявляй тесты прошедшими по чтению исходников. Не изменяй тесты, чтобы скрыть регрессию.

## Результат окна

Нужен применимый код в GitHub, а не обещание фоновой работы. В отчёте: branch/SHA/ссылка на PR или checkpoint; что проходит сквозным сценарием; точные команды и pass/fail/skip; какие capabilities пока fake/offline/live-not-verified; что именно передаётся MAX-задаче. Обнови docs/routes при новых entrypoints и CHANGELOG.

Не блокируй всё ядро ожиданием MAX/секретов/live imagegen. Не публикуй в реальные каналы без отдельной явно разрешённой canary-постановки. Не разворачивай сервис и не переключай EventsBot production из этого окна автоматически. До исчерпания окна продолжай реализацию следующих стадий; при остановке сохрани точный работающий checkpoint и следующий конкретный шаг.
