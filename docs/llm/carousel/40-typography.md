# 40 · Типографика и леттеринг

## Шрифты пакета и роли

| Шрифт | Характер | Роль | Начертания |
|---|---|---|---|
| Oswald | узкий гротеск | сильные заголовки, лозунги, числа | 200–700 |
| Unbounded | широкий display | обложка, короткие слова-акценты, цифры | 200–900 |
| Montserrat | геометрический гротеск | тело, подписи, рубрики | 100–900, italic |
| PT Serif | антиква | цитаты, документальный тон, подписи источников | 400/700, italic |

Пары: Oswald + Montserrat (по умолчанию, плакат-документ); Unbounded + Montserrat (современно, мало текста); Oswald + PT Serif (история, архив, цитаты); Unbounded + PT Serif (контраст, редакционно). Не больше 2 семейств + генеративный леттеринг на историю.

## Шкала кеглей (карточка 1080 px)

| Уровень | Кегль, px | Интерлиньяж | Трекинг | Применение |
|---|---|---|---|---|
| Display | 180–320 | 0.90–1.0 | caps −1…+1 % | 1–3 слова, обложка/пауза |
| H1 | 96–140 | 1.0–1.05 | caps +1…+3 % | заголовок карточки |
| H2 | 60–84 | 1.1 | 0…+2 % | подзаголовок |
| Body | 34–42 | 1.3–1.4 | 0 | тело, ≤ 35 слов |
| Caption | 24–28 | 1.35 | +2…+4 % | источник, рубрика (мин. 24!) |

Мельче 24 px на 1080 — не читается на телефоне. Длина строки тела 22–32 знака. Заголовок капсом — только узкие/широкие гротески, не антиква. Висячие предлоги («в», «на», «и») переносить на следующую строку.

## Сильная типографика (обязательна в каждой истории)

Минимум один момент из: (а) Display-слово ≥ 220 px; (б) карточка только из текста; (в) слово через шов (S05); (г) число-герой (95-infographics); (д) генеративный леттеринг. Контраст масштаба на карточке ≥ 1:3 (Display/H1 к Body).

**Плотность:** узкий (Oswald) — длинные заголовки в узкой колонке, сильный вертикальный ритм; широкий (Unbounded) — 1–2 слова, горизонтальный «удар»; смешивать в одной строке нельзя.

**Текст поверх фото:** `paint-order="stroke"` с обводкой 6–12 px цвета фона либо скрим; тень 0 4 16 rgba(0,0,0,.35) только для белого текста на фото.

## Генеративный леттеринг

Когда: обложка, лозунг/цитата, слово-образ (рельеф по бетону, неон, мел, вышивка, плакат 70-х, рукопись). Не для тела и не для фактов-чисел (риск ошибки буквы).
Процедура: (1) точная строка; (2) промпт по шаблону 60-generation §4 с фоном зоны; (3) сверка каждой буквы на `render(region)`; ошибка в букве — перегенерация с уточнением, не правка поверх; (4) встраивание — целым блоком на фоне зоны или страйпами по bbox строк (70-montage §4).


## Шесть направлений кириллической типографики


В каждой истории нужен хотя бы один сильный типографический момент; возможна целая карточка без медиа. Семь проверенных baseline-семейств сохранены: **Oswald, Golos Text, Inter, Source Serif 4, Manrope, Lora, Literata**. Новые кандидаты расширяют характер, не заменяют базу.

| Направление | Стартовые кандидаты и роли | Когда пробовать | Что смотреть |
|---|---|---|---|
| D01 · Condensed / узкий плакат | **Oswald** для display + **Golos Text** для пояснения | Короткая сильная фраза, вертикальный ритм, плотный акцент | Просветы букв после уменьшения, длину русского слова и ритм строк; не сжимать обычную гарнитуру по горизонтали ради имитации condensed |
| D02 · Neutral / ясный гротеск | **Inter**, **Golos Text** или **Manrope**; выбрать роли, а не смешивать все автоматически | Информация, подписи, спокойная основа рядом с выразительным объектом | Воспринимаемую высоту и массу, различие ролей, реальные цифры/знаки; «нейтральный» не означает отсутствие сильного масштаба |
| D03 · Serif / редакционный | **Source Serif 4**, **Lora** или **Literata** + Inter/Golos Text для поддержки | История места, цитата, вдумчивая типографическая пауза | Тонкие детали, интервалы, курсив только из реального ресурса; у variable-версий фиксировать использованные оси |
| D04 · Wide / широкий монументальный | **Unbounded** + Golos Text/Inter | Короткое имя, число или фраза как большая форма | Длинные слова и переносы, объём занимаемой площади; не жертвовать пояснением ради ширины display |
| D05 · Script / авторская рукописность | **Caveat** либо **Marck Script** + Golos Text/Manrope | Небольшая цитата, личная реплика, подпись как часть композиции | Кириллическую узнаваемость, соединения и строковый ритм на 360/320 px; это стилизация, не доказательство настоящего автографа |
| D06 · Generated lettering | Dot создаёт выразительную надпись: узкую, широкую, фактурную, рукотворную или пространственную; typeset/hybrid остаются доступными | Обложка, поворот, typography-only или metric hero; направление задаёт модель по смыслу | Точный canonical text, OCR + визуальное прочтение финального монтажа, кромки, маски и миниатюру. Метрики шрифта не доказывают качество сгенерированных букв |

Палитра не закрепляется навсегда за направлением. Например, D01 можно сравнить на PAL02 и PAL05, D03 — на PAL01/PAL04/PAL07, D04 — на PAL08/PAL12; это гипотезы для скетча, не предписания. Рукописный или сгенерированный текст не обязан выглядеть как готовая гарнитура. Для каждого выбранного компонента сохраняются точная строка и происхождение результата.


## Шрифты: источники и границы


У всех десяти перечисленных семейств официальный Google Fonts metadata объявляет **cyrillic**; SIL OFL **1.1** подтверждена соответствующими OFL.txt. Семь baseline-семейств проверены в основном исследовании; три новые пары METADATA/OFL прочитаны непосредственно при подготовке этого каталога. Это проверка официальной поставки, **не проверка cmap каждого бинарного файла или всех нужных глифов**. Перед использованием проверяется выбранный файл и реальный текст, включая Ё/Й/№/₽, даты и смешанную кириллицу/латиницу.

| Семейство | Подтверждённый контекст | Первичные файлы |
|---|---|---|
| Oswald | База; узкий display | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/oswald/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/oswald/OFL.txt) |
| Golos Text | База; спокойный основной текст | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/golostext/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/golostext/OFL.txt) |
| Inter | База; нейтральная иерархия | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/inter/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/inter/OFL.txt) |
| Source Serif 4 | База; редакционная антиква | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/sourceserif4/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/sourceserif4/OFL.txt) |
| Manrope | База; геометрический гротеск | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/manrope/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/manrope/OFL.txt) |
| Lora | База; антиква для акцента/цитаты | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/lora/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/lora/OFL.txt) |
| Literata | База; редакционное чтение | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/literata/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/literata/OFL.txt) |
| Unbounded | Новая проверка; normal, wght 200–900; cyrillic + cyrillic-ext | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/unbounded/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/unbounded/OFL.txt) |
| Caveat | Новая проверка; normal, wght 400–700; cyrillic + cyrillic-ext | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/caveat/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/caveat/OFL.txt) |
| Marck Script | Новая проверка; normal 400; cyrillic; cyrillic-ext не объявлен | [METADATA.pb](https://github.com/google/fonts/blob/main/ofl/marckscript/METADATA.pb) · [OFL.txt](https://github.com/google/fonts/blob/main/ofl/marckscript/OFL.txt) |

Для Marck Script в OFL указан Reserved Font Name «Marck Script»; в metadata не объявлена расширенная кириллица. Это не означает отсутствие конкретного знака: ответ даёт проверка файла/строки. Unbounded и Caveat поставляются как variable normal; Marck Script — normal 400. Не приписываем им дополнительные начертания или синтетический курсив как отдельную проверенную поставку.

Новые metadata указывают реальные upstream-источники: [Unbounded](https://github.com/googlefonts/unbounded/tree/f3ec43228a864a72487e41552e2140efab9884ea), [Caveat](https://github.com/googlefonts/caveat/tree/59745e818ef7973e11e70cb1358d0e902b56c5fc), [Marck Script](https://github.com/googlefonts/marckscript/tree/f4e66d73d1cc7190be547d491b99a0979c60fb10). На сервере сохраняются фактически использованные bytes, версия и лицензия; каталог не подменяет font pack.
