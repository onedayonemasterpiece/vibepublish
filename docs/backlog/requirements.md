Автогенератор видеосторис vibepublish
отдельный телеграм бот для управления (работать должен на том же сервере)

по аналогии с /kenigsberg (внимательно проанализируй реализацию и возьми оттуда лучшее, не изобретай нового)
Генерировать в 720p
с субтитрами
выбирать лучшие видеоотрезки из имеющихся
сихнонизация со звуком (переходы с видео на видео на сильные доли музыки)
музыка берётся из датасета, выбирается случайным образом
генерация сама на kaggle
должен быть процесс согласования перед публикацией
должно быть улучшение качество видео (делать по уже склеенным футажам но до нанесения субтитров)
итог должен публиковаться в сторис и в каналы
При заливе видео в датасет должно быть выделение координат из видео
Подключи к боту контроль лимитов запросов к нейросетям
Создай отдельный .env файл в который я добавлю секреты для этого бота
Внедри возможность делать гео-зависимый контент, например создать видеоролик на основе текущих фактических координат или усреднённых координат последних нескольких загруженных в базу роликов
гео-зависимость один из способов создание сюжета
Используй Teleton я тебе дам в ENV сессию
Создай cherkin сценарии для отладки (во время отладки склеивай не более 3 футажей)
Должно быть понятие сюжета. Сюжет может быть дополнен множеством комментариев, как текстовых, так и голосовых (сделай распознание из голоса в текст), далее на основе всех комментариев сформируй текст рассказа, который точно уложится в ролик не более 55 секунд
Текст должен быть без нейросетевых штампов
Сделай подключение к википедии и викимедиа по координатам, выявляя достопримечательности рядом, но не подмешивай их бездумно, при проработке сюжета покажи список что нашёл и дай его подтвердить или отфильтровать (кнопками-галочками), чтобы в сюжет не попало лишнее
Сюжет может быть зависимым от времени или нет (использовать старые футажи по координатам или словам поиска или нет), т.е. к примеру использовать только сегодняшние футажи или все или только летние например но за все года






Ниже требования по обработке качества видео
# Требования к модулю улучшения визуального качества видео 720p без апскейла

## Цель

Модуль должен улучшать видимое качество видео 720p без изменения разрешения, fps и длительности. Основной эффект: умеренное удаление шума/компрессионной грязи, лёгкое повышение резкости, аккуратное усиление локального/глобального контраста и насыщенности без “пережаривания” картинки.

Запрещено:

* увеличивать разрешение финального видео;
* менять fps без явного требования;
* удалять или пересжимать аудио без необходимости;
* применять агрессивный AI-enhancement по умолчанию;
* делать лица “пластиковыми” или менять узнаваемость персонажей;
* применять frame-by-frame AI без проверки на мерцание.

---

## Базовый стек

Обязательные зависимости:

```bash
apt-get update && apt-get install -y ffmpeg

pip install -U \
  opencv-python-headless \
  numpy \
  tqdm \
  scikit-image \
  imageio-ffmpeg
```

Опциональные зависимости для AI-режима:

```bash
pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -U basicsr facexlib gfpgan
pip install -U realesrgan
```

Важно: `noisereduce` не использовать для визуального enhancement. Это аудио-библиотека, не модуль улучшения изображения.

---

## Архитектура пайплайна

Пайплайн должен иметь 3 режима:

1. `fast_safe` — дефолтный режим FFmpeg, быстрый и стабильный.
2. `opencv_custom` — покадровый режим для более тонкой обработки.
3. `ai_optional` — тяжёлый GPU-режим, только по явному флагу.

Дефолт: `fast_safe`.

---

## Режим 1: fast_safe / FFmpeg

Использовать как основной production-пресет.

Команда:

```bash
ffmpeg -y \
  -i input.mp4 \
  -map 0:v:0 -map 0:a? \
  -vf "hqdn3d=1.5:1.2:2.5:2.0,unsharp=5:5:0.45:3:3:0.0,eq=contrast=1.04:brightness=0.00:saturation=1.05:gamma=1.00,format=yuv420p" \
  -c:v libx264 \
  -preset slow \
  -crf 18 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  -c:a copy \
  output.mp4
```

Параметры по умолчанию:

```yaml
ffmpeg_fast_safe:
  denoise:
    filter: hqdn3d
    luma_spatial: 1.5
    chroma_spatial: 1.2
    luma_temporal: 2.5
    chroma_temporal: 2.0

  sharpen:
    filter: unsharp
    luma_matrix: "5x5"
    luma_amount: 0.45
    chroma_matrix: "3x3"
    chroma_amount: 0.0

  color:
    filter: eq
    contrast: 1.04
    brightness: 0.00
    saturation: 1.05
    gamma: 1.00

  encode:
    codec: libx264
    preset: slow
    crf: 18
    pix_fmt: yuv420p
    audio: copy
    keep_resolution: true
    keep_fps: true
```

Диапазоны настройки:

```yaml
allowed_ranges:
  hqdn3d_luma_spatial: [1.0, 3.0]
  hqdn3d_chroma_spatial: [0.8, 2.2]
  hqdn3d_luma_temporal: [1.5, 4.5]
  hqdn3d_chroma_temporal: [1.2, 3.5]
  unsharp_luma_amount: [0.25, 0.70]
  contrast: [1.00, 1.08]
  brightness: [-0.02, 0.02]
  saturation: [1.00, 1.10]
  crf: [17, 20]
```

Не использовать по умолчанию:

```yaml
avoid_by_default:
  brightness_above: 0.03
  saturation_above: 1.12
  unsharp_luma_amount_above: 0.85
  heavy_blur_or_temporal_average: true
```

---

## Режим 2: opencv_custom

Использовать, когда нужно управлять кадрами вручную.

Рекомендуемые настройки:

```yaml
opencv_custom:
  color_space:
    internal: BGR
    contrast_space: LAB
    clahe_channel: L

  denoise:
    method: fastNlMeansDenoisingColored
    h: 5
    hColor: 5
    templateWindowSize: 7
    searchWindowSize: 21
    max_h: 8

  clahe:
    enabled: true
    clipLimit: 1.6
    tileGridSize: [8, 8]
    max_clipLimit: 2.2

  sharpen:
    method: unsharp_mask
    gaussian_sigma: 1.1
    amount: 0.35
    max_amount: 0.55

  output:
    write_intermediate_frames_lossless: false
    final_encode_with_ffmpeg: true
    keep_audio: true
```

Правило: OpenCV не должен финально кодировать MP4 через `mp4v`, если есть возможность использовать FFmpeg. OpenCV может генерировать кадры или промежуточное видео, финальный контейнер и кодек должен делать FFmpeg.

---

## Режим 3: ai_optional

AI-режим использовать только при явном флаге:

```yaml
ai_optional:
  enabled_by_default: false
  require_gpu: true
  target_resolution_change: false
  enforce_original_width_height: true
  check_temporal_flicker: true
```

### Real-ESRGAN

Использовать только для сильно сжатого, старого или визуально слабого материала.

```yaml
realesrgan:
  enabled: false
  model_general: RealESRGAN_x4plus
  outscale: 1
  tile: 256
  tile_pad: 10
  fp32: false
  face_enhance: false
  output_resize_to_original: true
  warning: "May hallucinate texture and cause flicker on video"
```

Правила:

* `outscale=1` допустим, но финальный размер всё равно обязательно проверять и приводить к исходному 1280x720.
* `face_enhance=false` по умолчанию.
* Не использовать на каждом ролике автоматически.
* После обработки собрать видео через FFmpeg с `-c:a copy`.

### Restormer

Использовать только для denoise/deblur задач, когда есть явная проблема шума или размытия.

```yaml
restormer:
  enabled: false
  tasks_allowed:
    - Real_Denoising
    - Motion_Deblurring
    - Defocus_Deblurring
  process_mode: extracted_frames
  temporal_consistency_check: required
  output_resize_to_original: true
  warning: "Image model; frame-by-frame processing can flicker"
```

### RealBasicVSR / BasicVSR++

Использовать как экспериментальный temporal-AI режим.

```yaml
video_ai_temporal:
  enabled: false
  preferred_for:
    - compressed_video
    - noisy_video
    - temporal_flicker_sensitive_content
  models:
    - RealBasicVSR
    - BasicVSR++
  strict_no_upscale: true
  output_resize_to_original: true
  install_complexity: high
```

---

## Preset selection logic

```yaml
preset_selection:
  default:
    use: ffmpeg_fast_safe

  if_video_is_clean_generated_720p:
    denoise_strength: low
    sharpen_amount: 0.25
    contrast: 1.02
    saturation: 1.03

  if_video_has_compression_noise:
    denoise_strength: medium
    hqdn3d: "2.0:1.5:3.2:2.4"
    sharpen_amount: 0.35

  if_video_is_soft_or_slightly_blurry:
    denoise_strength: low
    sharpen_amount: 0.55
    contrast: 1.04

  if_video_is_low_light:
    denoise_strength: medium
    saturation: 1.03
    contrast: 1.03
    brightness: 0.00
    avoid_aggressive_clahe: true

  if_video_has_faces_closeup:
    face_enhance: false
    allow_gfpgan_only_by_explicit_flag: true

  if_max_quality_requested:
    try_ai_optional: true
    run_short_sample_first: true
    compare_before_after: true
```

---

## Quality control

После обработки модуль должен проверить:

```yaml
quality_control:
  resolution_unchanged: required
  fps_unchanged: required
  duration_delta_max_seconds: 0.1
  audio_preserved_if_present: required
  no_black_frames: required
  no_duplicate_frame_spikes: recommended
  no_visible_flicker: required_for_ai
  no_oversharpen_halos: required
  no_crushed_blacks_or_clipped_whites: required
```

Для каждого ролика сохранять metadata:

```yaml
metadata_log:
  input_width: true
  input_height: true
  output_width: true
  output_height: true
  input_fps: true
  output_fps: true
  filters_used: true
  encode_crf: true
  processing_mode: true
  ai_model_if_used: true
```

---

## Главный дефолт

Автогенератор должен по умолчанию использовать этот безопасный пресет:

```yaml
default_video_enhancement:
  mode: ffmpeg_fast_safe
  keep_resolution: true
  keep_fps: true
  keep_audio: true
  target_resolution: original
  denoise: mild_temporal
  sharpen: mild
  contrast: mild
  saturation: mild
  ai_enhancement: false
  face_restoration: false
  final_codec: libx264
  crf: 18
  preset: slow
```
