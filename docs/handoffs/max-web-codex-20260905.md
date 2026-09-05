# VibePublish: отдельная задача MAX Web — 2026-09-05

Работай в Codex самостоятельно, одной bounded задачей. Нужны код, автотесты и сохранённая MAX-дельта, не новый аудит. Ядро, Telegram/VK, MCP и VisualService не переписывать и не делегировать. Не запускать imagegen, production deployment, миграцию EventsBot и реальные публикации.

Repo: https://github.com/onedayonemasterpiece/vibepublish
MAX-ветка: `work/vibepublish-max-web-20260904` — продолжить существующую; если отсутствует, создать от актуального main. Сначала fresh-read main, MAX branch/PR, core branch `work/vibepublish-core-20260904`, PR #1 с комментариями и diff. Без reset/force-push и перезаписи параллельных изменений. Выбрать минимально достаточную доступную модель/effort, не high по умолчанию.

## Каноническая база

Прочитай AGENTS.md, README.md, docs/README.md, docs/routes.yml, затем `docs/handoffs/max-web-codex-20260904.md` ЦЕЛИКОМ. Все его функциональные сценарии, автомат состояний, ограничения, M01–M12 и Definition of done сохраняются. Этот файл уточняет фактическую передачу core, live-разрешения и критерии доказательств; при конфликте он приоритетнее старой постановки.

Также прочитай `docs/operations/social-runtime.md`, social-operations README, implementation-design-v1.md, mcp-contract-v1.md, forwarding-and-editorial-profiles-v1.md, acceptance-tests-v1.md, фактический `adapters/port.py` и вызовы порта в worker.

К задаче приложить `vibepublish-native-visual-20260905.zip`, проверить MANIFEST.json и хеши. Это полный локальный snapshot ядра для integration tests, НЕ доказательство сохранения на remote. Последний проверенный remote core HEAD: `60712c41cee5975c24c4e5346b22857f39c035ec`; полный LOCAL HEAD архива: `870e2a4304c57ef5dd7152de63df1db6431a942b`. Checkpoints не замораживают ветки.

Единственный общий порт: `adapters/port.py`, последний изменивший его LOCAL commit `25de851b911d02fc9ece2a7e193743758bfa48c1`; SHA-256 файла `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`. В нём есть `RemoteItem.native_target`, `provider_media`, `member_ids`; ранний remote seed старее. Используй существующие ProviderRequest/Prepared/Observation/ReadRequest/ReadPage/Hooks/ProviderAdapter, не создавай копию контрактов.

Если полный core отсутствует на remote, собери отдельный локальный integration checkout из проверенного архива и MAX-дельты. Это не блокирует driver/browser tests. MAX-коммиты не должны включать весь core-архив: запись core была заблокирована в ChatGPT, данная задача не служит обходом защиты. Отчёт обязан разделять local assembled-tree tests и remote CI. Изменение общего порта требует минимальной согласованной дельты, не второго runtime.

## Реализовать

MAX API не подключать и согласования не ждать. Нужен детерминированный Web/Playwright adapter поверх разрешённого persistent profile: inspect / prepare / execute / read / reconcile. Приоритет: точные account/target; now text, text+image, ordered multi-image; native schedule; live queue, включая отложенные других редакторов в разрешённом канале; in-place edit/reschedule/cancel и delete при фактической поддержке. Видео, rich content, stories, forwarding, discovery, analytics оставить в явной capability matrix. Native forward не подменять копированием.

НЕТ планировщика будущих отправок. Worker сейчас создаёт отложенный элемент в MAX. Прошедшее/слишком близкое время блокируется, никогда не превращается в now. Без native schedule/readback — unsupported/needs_review, не локальный timer. Reschedule не заменять delete+create.

Auth, права, durable receipt, ledger, idempotency, operation/attempt IDs, frozen targets и dispatch принадлежат core. Awaitable emit_progress/checkpoint/before_effect обязательны. Финальный submit — только после успешного before_effect и durable dispatch marker. При отказе callback/DB — zero mutation. После возможного воздействия/timeout/crash — read/reconcile, не повторный submit. Старый одинаковый пост не доказывает новую отправку; несколько совпадений оставляют outcome_unknown. Права/аккаунт/канал проверять повторно перед воздействием.

Один владеющий процесс/side-effect lane на profile, реальный межпроцессный lock. Lease expiry не разрешает повторную отправку; второй Chromium на userDataDir запрещён. MAX не блокирует независимые Telegram/VK events и первый новый status event.

Readback проверяет сохранённый элемент очереди/ленты, не composer/toast. Возвращай фактические remote identities, namespace, observed_at, время, текст и порядок provider media. Не выдумывай permalink и равенство хешей перекодированного изображения. Scoped readback не открывает посторонние чаты и приватные assets. QR/OTP/CAPTCHA — человек; credentials/cookies не экспортировать. EventsBot credentials не использовать.

## Проверки

Рабочие области: adapters/max/, tests/adapters/max/, tests/browser/max/, sanitized fixture pages, MAX runbook и минимальное wiring. Один существующий GitHub-hosted CI, без self-hosted runner и второго workflow/runtime/ledger.

Обязателен настоящий Playwright/Chromium на локальных fixture pages с задержками, virtualization и rerender. Mocked page object недостаточен. Выдуманный fixture DOM проверяет автомат состояний, но НЕ совместимость с live MAX; реальные locators подтверждаются только осмотренным разрешённым UI.

Покрой M01–M12 старой постановки и дополнительно callback failure, отзыв прав между prepare/submit, too-close time, changed item/CAS, чужой scheduled в разрешённом канале, межпроцессную конкуренцию и изоляцию чужих каналов/assets.

Сквозной тест: настоящий core MCP ClientSession, Telegram/VK fixture providers и MAX driver на browser fixture. MAX задержан, Telegram/VK events уже доступны. После настоящего process crash post-submit новая operation/повторный клик не создаются; состояние fixture UI наблюдается независимо от памяти процесса.

## Live-разрешения и итог

Эта задача НЕ разрешает live writes/canaries и deployment. При отсутствии логина продолжай offline реализацию. Read-only обследование MAX — только через явно предоставленный разрешённый profile; личные browser profiles самостоятельно не выбирать.

Подготовь отдельно заблокированный без разрешения и test destination allowlist canary: native schedule → остановить все VibePublish процессы → внешним наблюдением подтвердить публикацию самим MAX → рестарт без дубля. Сейчас не запускать.

Сохраняй небольшие MAX-only коммиты, remote readback SHA/файлов, один MAX PR; обнови canonical MAX status, docs/routes.yml и CHANGELOG. Evidence/artifacts не коммить. Отчёт: exact branch/remote SHA/PR/CI conclusion, LOCAL integration core SHA, команды pass/fail/skip, browser versions; отдельно unit/browser-fixture/live-read/live-write-not-run, capability matrix, unknown outcomes и один конкретный следующий пакет. Не писать «MAX готов» по fixtures. При блокировке записи не обходить защиту: применимый MAX-only patch и точная диагностика.
