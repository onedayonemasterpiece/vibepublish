# 70 · Монтаж: SVG-рецепты

Холст — один SVG `width=N*1080 height=1350`, `viewBox="0 0 W 1350"`. Слои снизу вверх: подложка → фоновый объект/бренд → фото и вырезки → панели → текст → мосты-линии → номера/рубрики. Все изображения — `href="asset:ID"`. Шрифты — только пакетные (40-typography). Ниже — проверенные заготовки; подставляй координаты.

## §1 Подложка сегментами

```svg
<image href="asset:BG_1_3" x="0" y="0" width="3240" height="1350" preserveAspectRatio="xMidYMid slice"/>
<image href="asset:BG_4_5" x="3240" y="0" width="2160" height="1350" preserveAspectRatio="xMidYMid slice"/>
<!-- стык сегментов спрятан под мостом/объектом, не на резе карточек -->
```

## §2 Фото со скруглением

```svg
<defs><clipPath id="r1"><rect x="1180" y="620" width="760" height="520" rx="32"/></clipPath></defs>
<image href="asset:PHOTO" x="1180" y="620" width="760" height="520" preserveAspectRatio="xMidYMid slice" clip-path="url(#r1)"/>
```
Поворот «не ровно»: оберни в `<g transform="rotate(-3 1560 880)">`.

## §3 Маска сложной формы / вырезка объекта

Органическая маска (капля/арка) — `clipPath` с `path`:
```svg
<defs><clipPath id="blob"><path d="M960 300 C1300 220 1560 420 1520 760 C1480 1100 1100 1200 900 1040 C700 880 640 380 960 300 Z"/></clipPath></defs>
<image href="asset:PHOTO" x="600" y="200" width="1100" height="1050" preserveAspectRatio="xMidYMid slice" clip-path="url(#blob)"/>
```
Вырезка объекта по контуру: (а) PNG с прозрачностью — просто `<image>`; (б) объект на ровном фоне зоны — `<image>` без маски (фон совпадает с подложкой); (в) контур вручную — `clipPath` с `path` по силуэту (12–40 точек, растушёвка не нужна при совпадающем фоне). Единая тень под вырезкой: `filter` ниже.

## §4 Страйпы текста по bbox (генеративный леттеринг)

```svg
<defs><clipPath id="line1"><rect x="0" y="0" width="1600" height="210"/></clipPath>
<clipPath id="line2"><rect x="0" y="210" width="1600" height="210"/></clipPath></defs>
<g transform="translate(140 260)"><image href="asset:LETTERING" width="1600" height="420" clip-path="url(#line1)"/></g>
<g transform="translate(980 520)"><image href="asset:LETTERING" x="0" y="-210" width="1600" height="420" clip-path="url(#line2)"/></g>
```
Строки одной надписи можно сдвинуть ступенькой и/или провести через шов.

## §5 Скрим и обводка для текста на фото

```svg
<defs><linearGradient id="scrim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".62"/></linearGradient></defs>
<rect x="0" y="820" width="1080" height="530" fill="url(#scrim)"/>
<text x="72" y="1100" font-family="Oswald" font-weight="700" font-size="112" fill="#fff" paint-order="stroke" stroke="#1a1a1a" stroke-width="8">ЗАГОЛОВОК</text>
```

## §6 Единый цвет и зерно для разных фото

```svg
<defs>
 <filter id="grade"><feColorMatrix type="matrix" values="0.9 0.1 0 0 0.02  0.05 0.9 0.05 0 0.01  0 0.1 0.85 0 0  0 0 0 1 0"/></filter>
 <filter id="duo"><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncR type="table" tableValues="0.12 0.95"/><feFuncG type="table" tableValues="0.13 0.93"/><feFuncB type="table" tableValues="0.16 0.88"/></feComponentTransfer></filter>
 <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#000" flood-opacity=".28"/></filter>
</defs>
```
`grade` — тёплое выравнивание; `duo` — дуотон (цвета из палитры: тени = T, света = B) для архивных снимков; `shadow` — общая тень вырезок/панелей. Один фильтр на все фото истории.

## §7 Фоновое слово / бренд

```svg
<text x="1500" y="900" font-family="Unbounded" font-weight="800" font-size="420" fill="#000" fill-opacity=".07" letter-spacing="-8">ПОЛЮБИТЬ</text>
```

## §8 Нить через холст

```svg
<path d="M140 1180 C900 1040 1300 1260 2160 1150 S3600 1020 4320 1160 S6200 1260 7400 1120" fill="none" stroke="#C8102E" stroke-opacity=".7" stroke-width="6" stroke-linecap="round"/>
<circle cx="2160" cy="1150" r="14" fill="#C8102E"/>
```

## §9 Панель через шов

```svg
<rect x="760" y="140" width="1260" height="640" rx="64" fill="#F4F1EA"/>
```

## §10 Иконка inline

Вставь очищенный SVG иконки из `get(scope:icon)` в `<g transform="translate(x y) scale(s)">…</g>`, цвет — `fill`/`stroke` из палитры.

## §11 Вписывание фрагмента по месту (для F1) и растушёвка края

```svg
<defs>
 <linearGradient id="fadeX" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".06" stop-color="#fff"/><stop offset=".94" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
 <mask id="feather" maskUnits="userSpaceOnUse" x="1180" y="180" width="1400" height="420"><rect x="1180" y="180" width="1400" height="420" fill="url(#fadeX)"/></mask>
</defs>
<image href="asset:TITLE_ON_BG" x="1180" y="180" width="1400" height="420" mask="url(#feather)"/>
```
Сгенерированный по фрагменту кусок ставится в те же координаты, что и вырезанный фон; маска с растушёвкой по краям 6 % ширины (24–48 px) прячет мелкий сдвиг тона. Фоновые слои помечай `id="bg-…"`, чтобы рендерить фон отдельно (`only`).

## Порядок проверки после монтажа

`render(view:master)` → каждый шов `render(view:region)` → каждая карточка `render(card:N)` → 90-review.
