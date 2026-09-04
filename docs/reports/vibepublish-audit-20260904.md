# Независимый аудит VibePublish — 4 сентября 2026

Статус требований владельца: `Fixed`. Новые проектные решения: `Not confirmed by user`. Реализация социального сервиса: `Not done`.

## Вердикт

Исходный проект — полезный набор требований и заготовка, но не готовое техническое задание для безопасного переноса в код. Основные идеи предыдущего проектирования правильные: отдельный сервис, одна высокоуровневая публикация, независимые результаты по площадкам, явная неопределённость, MAX Web и imagegen. Проблема не в этих принципах, а в незакрытых переходах между ними.

После этого пакета можно начинать поэтапную реализацию по [implementation design](../features/social-operations/implementation-design-v1.md). Это не разрешение объявить runtime готовым, не доказательство работы MAX и не результат сравнения поколений моделей.

## Что действительно проверено

На момент начала работы `main` точно совпадал с переданным commit `a2a089f320049b6413cd2f635fd8e93ab7aee888`.

Проверены дерево репозитория, AGENTS/README/routes, основной social contract, полный handoff, donor map, LLM feature, исходные требования видеогенератора, зависимости и инвентарь тестов. В существующем коде прицельно проверены инициализация/публичный вызов GoogleAIClient, резервирование/mark_sent/finalize, обработка ответа и SQL reserve/sweep. Это архитектурный аудит всего проекта и статическое ревью критических участков существующего кода, не построчный аудит всех SDK/донорских файлов и не penetration test.

Связанная карточка IdeaHub прочитана непосредственно в GitHub. Донорский `events-bot-new/main` разрешён в `2334917ca30f803babad0f593fbffd8ad39fb709`; его широкие capabilities в donor map — инвентарь для переноса, а не независимо перепроверенная здесь live-паритетность.

Codex/другие агенты не запускались. Подключения соцсетей, секреты, MAX-профили и imagegen-runtime не исследовались и не изменялись. Прямое клонирование в локальную среду оказалось недоступно; чтение и запись GitHub выполнялись через connector. Локальные проверки нового контракта не означают запуска старого приложения.

## Классификация требований

**Уже присутствовало:** Telegram/VK/MAX; выделенный сервис; собственные подключения; aliases/sets; один вызов публикации; donor reuse без runtime-зависимости; частичный успех; неизвестный исход; `$imagegen` вместо Google Imagen; внешние пользователи; версионированный skill.

**Требовало уточнения:** окончательный каталог MCP; права чтения внешних пользователей; расписание; различие принятия и фактической публикации; media readback; approval/selection; схема изоляции и срок внедрения multi-tenant; роль Google limiter; границы полного продукта и первого рабочего среза.

**Отсутствовало:** точная фиксация состава set и планов; двухуровневая идемпотентность; отмена в гонке с отправкой; отзыв прав после native scheduling; границы доверия media/DOM; единый профиль MAX и fencing; эксплуатационные восстановления; перенос уже отложенных публикаций; машинно проверяемые schemas и корпус пользовательских задач; канонический раздел видеогенератора.

## Реестр проблем и решений

| ID | Приоритет | Проблема на исходном checkpoint | Решение / куда включено |
|---|---|---|---|
| A01 | P0 | README закрепляет девять методов и convenience aliases; handoff прямо отменяет этот выбор и предлагает другую шестерку | Один выбранный восьмиметодный контракт; никаких synonym tools; сравнение вариантов и статус измерений в MCP design |
| A02 | P0 | В основном feature внешний tenant получает чтение связанных ресурсов; correction требует запрета чтения по умолчанию | Explicit read grants даже для собственных подключений; служебный readback не равен доступу к ленте |
| A03 | P0 | В delivery sequence внешние ограничения оказываются последним этапом, хотя ими должны быть защищены первые записи | tenant/principal/binding/policy epoch входят в первый core batch |
| A04 | P0 | Нет точного durable dispatch point и правила takeover после истечения lease | Сохранить dispatch_started до воздействия; после него observation-first; fencing не выдаётся за удалённую транзакцию |
| A05 | P0 | Один digest пытается включить ещё не существующий результат генерации/выбор кандидата | Request digest отдельно от immutable execution revision/plan digest |
| A06 | P0 | Набор каналов и права могут измениться между постановкой и отправкой | Заморозка concrete set members; права перепроверяются; нельзя перенаправить старое задание изменением alias/set |
| A07 | P0 | Native/service scheduling, late behavior, timezone и отмена не сведены в исполняемые правила | Service default; один backend на child; RFC3339 offset; hold при опоздании; отдельные cancel/delete и гонки |
| A08 | P0 | Отзыв локальных прав может оставить уже отправленную native-очередь провайдера | Cleanup authority + readback; явное remote_schedule_may_remain при невозможности отмены |
| A09 | P0 | MAX описан принципами, но не определены профиль, commit boundary, совпадающие посты и доказательство результата | Конечный автомат, один профиль/side-effect lane, проверка аккаунта/канала, bounded recovery и строгий readback |
| A10 | P0 | Multi-provider успех можно спутать с атомарностью или затерять неизвестный исход в partial | All-target deterministic preflight; независимый runtime fan-out; unknown имеет приоритет в parent projection |
| A11 | P1 | Требование проверки remote SHA не учитывает перекодирование медиа платформой | Разделены source digest, provider-object binding, порядок/число и visual correspondence; непроверенное не выдаётся за pass |
| A12 | P1 | Approval не связан с candidate/revision/rights epoch; select может фактически подтвердить другой пост | Одноразовые scoped tokens, точный plan digest, новая проверка прав и времени перед resume |
| A13 | P1 | «Один вызов» скрывает реальную проблему передачи байтов из ChatGPT на сервер | Owned refs / signed HTTPS / authenticated upload tickets; локальный путь не считается доступным файлом |
| A14 | P1 | Нет проработанного operational восстановления и безопасного cutover из EventsBot | Consistent backup, restore без writes, reconcile unknown, freeze/import old queue, единственный execution owner |
| A15 | P1 | Broad donor list ошибочно может восприниматься как уже реализованный API и разрешения | Матрица capability per connection/target/surface, даты наблюдения и отдельные offline/live gates |
| A16 | P1 | В корне tests только `test_google_ai_import.py`; нет доказательств concurrent quota, social recovery, schema usability | Новый executable design/corpus; отдельные обязательные runtime/security/browser/weak-agent gates |
| A17 | P1 | Исходный продукт видеосторис остался в неразмеченном backlog и не попал в feature routing | Новый canonical video-stories contract; Kaggle/render/approval сохраняются, публикация только через общий core |
| A18 | P1 | Imagegen ещё не имеет проверенного здесь server invocation/artifact contract | Точный typed executor boundary, fake/live separation и обязательный DevCoveer canary; Google Imagen не подставляется |
| A19 | P1 | Набор моделей/зависимостей/квот назван существующим, но нет lockfile и проверки совместимости deployment | Зафиксировать exact packages/browser и реальные capability probes в batch A/F; не полагаться на названия моделей в старых docs |
| A20 | P1 | Сокращение числа tools не гарантирует маленькие schemas и низкую ошибочность | Самодостаточные schemas с reachable `$defs`, scoped catalog, bootstrap budget, отдельный реальный weak-agent benchmark |

## Прицельное ревью существующего Google limiter

Эти находки **не исправлены кодом** в данном проектном пакете. Они не должны блокировать публикацию без опционального Google rewriting, но блокируют использование этого кода как доказанно безопасного общего quota service.

### G01 — гонка проверки лимита (P0 для общего quota service)

`migrations/002_google_ai_rpc_rollout.sql`, `google_ai_reserve`: счётчики сначала читаются обычными SELECT, затем сравниваются с лимитом, затем без условного предиката увеличиваются через UPSERT. Общая блокировка ключа/модели до проверки отсутствует.

Контрпример по исходному SQL: при rpm_used=9 и rpm=10 две транзакции читают 9, обе разрешают +1, обе увеличивают счётчик; итог 11. Одна транзакция на один RPC сама по себе не делает это безопасной проверкой лимита. Это статический вывод из последовательности SQL, не результат нагрузочного запуска.

Исправление для optional Supabase path: блокировать канонический key/model quota owner до проверки, в фиксированном порядке; либо делать условное атомарное резервирование и корректный rollback всей multi-counter reservation. Добавить параллельные тесты с реальным Postgres, включая пустой bucket и совпадающий request UID. Не переносить этот алгоритм в SQLite tenant quotas.

### G02 — fail-open accounting (P1)

`google_ai/client.py`: три fallback-флага по умолчанию включены. Локальный лимитер не даёт межпроцессной гарантии. Его счётчики изменяются через instance attributes; наличие общего lock не заменяет общей durable state.

Для оплачиваемых/shared-tenant операций: fail closed либо явно изолированная single-worker degraded policy с собственным жёстким бюджетом. Включённый Google adapter не должен скрывать потерю общего лимитера.

### G03 — недоказанная отправка и ложная компенсация (P1)

`_mark_sent` глотает ошибки/отсутствие RPC и позволяет продолжить вызов провайдера. `003_google_ai_sweep_stale.sql` компенсирует старые reserved rows с sent_at IS NULL. Поэтому при неудавшейся записи mark_sent возможна компенсация запроса, который фактически уже ушёл к провайдеру.

Правило: отказ durable mark_sent в строгом режиме запрещает отправку; неопределённый sent state удерживает резерв до reconciliation/консервативного settlement. Sweep не должен считать отсутствие маркера доказательством отсутствия внешнего воздействия.

### G04 — request_uid не является публичной идемпотентностью (P1)

`generate_content_async` создаёт новый UUID внутри каждого вызова и не принимает caller identity. Его idempotency comment относится к внутренним попыткам, не к повтору MCP/HTTP-команды. VisualService должен владеть устойчивым operation key и артефактом, а не доверять новому UUID gateway.

### G05 — неоднозначный текстовый результат (P1)

В `_call_provider/_extract_text` собираются тексты нескольких candidates, а крайний fallback делает `str(resp)`. Для structured recovery/editorial use нельзя считать сериализацию пустого/blocked ответа допустимым результатом. Выбирать один candidate по явному правилу, проверять finish/safety state, валидировать строгую схему и не переписывать контент в фазе отправки. Это дополнительное требование к исправлению gateway, не заявление о наблюдавшейся утечке.

## Что изменилось в проектировании

Основные гарантии теперь сформулированы как проверяемые постусловия, а не обещания: какой канал, какие байты были отправлены, что провайдер действительно показал, какой backend отвечает за расписание, что произойдёт после timeout, отзыва прав, выбора картинки и восстановления backup.

Нельзя честно гарантировать универсальное exactly-once воздействие на чужую платформу при потере ответа. Проект гарантирует durable identity, запрет слепого повторения, явную неопределённость и provider-specific reconciliation; оставшаяся неопределённость видна владельцу.

## Проверки и границы готовности

Исполняемый контракт и golden task corpus служат для проверки корректности схем, несовместимых аргументов и воспроизводимости заданий. Они не являются тестом работающего сервиса или экспериментом со слабой моделью. Финальный результат локального прогона и точная команда записываются в `docs/features/social-operations/mcp-contract-v1.md`.

Не выполнены и не заявляются выполненными: старый gateway test suite, реальный Postgres concurrency test, provider canaries, MAX browser test, imagegen invocation, model A/B benchmark, production deployment. Это явно определённые acceptance gates следующих этапов, а не скрытые архитектурные решения.

## Прямые источники

Все локальные ссылки ниже относятся к reviewed base `a2a089f320049b6413cd2f635fd8e93ab7aee888`, если не оговорено иное:

- `docs/features/social-operations/README.md` — исходный основной контракт.
- `docs/features/social-operations/analysis-handoff-20260904.md` — исправления владельца и реконструированный voice context.
- `docs/backlog/requirements.md` — исходные требования видеосторис и enhancement.
- `docs/features/llm-gateway/README.md`, `google_ai/client.py`, `migrations/002_google_ai_rpc_rollout.sql`, `migrations/003_google_ai_sweep_stale.sql`.
- `pyproject.toml`, `tests/test_google_ai_import.py`, корневое Git tree.
- IdeaHub: `ideas/product.vibepublish/idea-20260903-social-publishing-audio-and-browser-automation.md` — прочитанная связанная карточка. Все перечисленные в handoff исходные аудиофайлы заново не прослушивались.
- PostgreSQL concurrency reference: https://www.postgresql.org/docs/current/explicit-locking.html
- Остальные официальные protocol/browser/storage sources перечислены в implementation design.
