# Music Recommendation System

Desktop-приложение для локальной музыкальной библиотеки: импорт треков,
взаимодействия `Play / Skip / Like`, рекомендации и анализ музыкального стиля
с помощью MAEST.

## Что важно знать после клонирования

GitHub хранит исходный код и небольшие конфигурационные файлы, но не хранит:

- виртуальное окружение `.venv`;
- локальную базу `data/music.db`;
- аудиотеку `data/library/`;
- cookies YouTube;
- тяжёлый файл модели `data/models/maest/maest.onnx`.

Поэтому на новом компьютере зависимости и модель нужно подготовить один раз.
Повторно устанавливать их при каждом запуске не нужно.

## Требования

- Windows 10/11 x64;
- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- NVIDIA GPU и свежий NVIDIA Driver — рекомендуется для быстрого MAEST
  inference;
- Firefox — если нужно автоматически использовать YouTube-сессию;
- FFmpeg с shared DLL-библиотеками — для чтения аудио через TorchCodec.

PyTorch и `onnxruntime-gpu` устанавливаются как Python-зависимости проекта.
Отдельно устанавливать CUDA Toolkit обычно не требуется: CUDA-зависимости
поставляются вместе с PyTorch, но NVIDIA Driver должен быть установлен.

## Установка

Клонируй репозиторий и перейди в его папку:

```powershell
git clone https://github.com/Archezer/music-recommendation-system.git
cd music-recommendation-system
```

Установи зависимости из `uv.lock`:

```powershell
$env:UV_CACHE_DIR = "$pwd\.uv-cache"
uv sync --locked
```

Команда создаст `.venv` и установит в том числе:

- PyTorch с CUDA 12.6;
- TorchAudio и TorchCodec;
- ONNX Runtime GPU;
- PySide6;
- yt-dlp;
- библиотеки для notebook и визуализации.

### Проверка CUDA для ONNX Runtime

```powershell
uv run python -c "import torch, onnxruntime as ort; print('Torch CUDA:', torch.cuda.is_available()); print('ONNX providers:', ort.get_available_providers())"
```

Ожидаемый результат содержит:

```text
Torch CUDA: True
CUDAExecutionProvider
```

MAEST выбирает `CUDAExecutionProvider`, если он доступен, и использует CPU как
резервный вариант. Подробнее: [ONNX Runtime CUDA Execution Provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).

## FFmpeg и TorchCodec

Установи именно shared-сборку FFmpeg:

```powershell
winget install --id Gyan.FFmpeg.Shared -e
```

Полностью закрой и заново открой VS Code/PowerShell, затем проверь:

```powershell
ffmpeg -version
```

Если команда не найдена, добавь папку `bin` установленного FFmpeg в
пользовательский `PATH`. Нужны DLL-библиотеки `avcodec`, `avformat`, `avutil`
и другие, поэтому обычного Python-пакета `ffmpeg` недостаточно.

## Файл MAEST

Модель MAEST занимает больше 300 МБ и намеренно исключена из обычного Git.
Создай папку:

```powershell
New-Item -ItemType Directory -Force data\models\maest
```

Положи файл:

```text
data/models/maest/maest.onnx
```

В проект подключён обновлённый checkpoint
`discogs-maest-30s-pw-519l-2.onnx`. Файл `data/models/maest/maest.json` уже
входит в репозиторий и содержит названия 519 классов Discogs23. ONNX-файл
нужно передать отдельно или скачать из релиза проекта, когда он будет
опубликован.

## Запуск приложения

Запускай из корня проекта:

```powershell
$env:UV_CACHE_DIR = "$pwd\.uv-cache"
uv run python -m app.desktop
```

Папки `data/`, `data/library/` и база создаются автоматически при первом
запуске.

## Notebook с pipeline MAEST

Для наглядной проверки открой:

```text
notebooks/maest_pipeline.ipynb
```

В VS Code выбери kernel из `.venv`, затем выполни ячейки по порядку. Notebook
показывает:

```text
audio file
    -> 30-second overlapping windows
    -> log-mel spectrogram
    -> MAEST ONNX inference
    -> 519 genre scores
    -> ranked genres for the track
```

Текущие формы данных:

```text
windows:       (N, 480000)
mel:           (N, 1876, 96)
window_scores: (N, 519)
mean_scores:   (519,)
```

Итоговые предсказания фильтруются по `score >= 0.1`. Для каждого также
сохраняются rank и rank-weight. В базе и UI используется родительский жанр
(например, `Folk, World, & Country`), а поджанр используется рекомендациями
только при `score >= 0.25`. Это не позволяет слабому предсказанию вроде
`Flamenco` становиться главным жанром трека.

## YouTube: поиск и скачивание

Приложение поддерживает:

- поиск по названию;
- скачивание выбранного результата;
- скачивание по прямому YouTube URL;
- Firefox cookies как основной источник авторизации;
- локальный cookies-файл как резервный источник.

### Вариант 1: cookies из Firefox

1. Установи Firefox.
2. Войди в YouTube.
3. Открой YouTube в Firefox хотя бы один раз.
4. При скачивании приложение сначала попробует использовать Firefox-профиль.

Если появляется ошибка о невозможности скопировать cookies, полностью закрой
Firefox и повтори операцию. База cookies Firefox может быть заблокирована самим
браузером.

### Вариант 2: локальный cookies-файл

Если Firefox не сработал, экспортируй cookies YouTube в Netscape-формате и
сохрани файл по адресу:

```text
data/youtube_cookies.txt
```

Файл игнорируется Git и не должен отправляться на GitHub. Приложение подхватит
его автоматически. Также путь можно задать переменной:

```powershell
$env:YTDLP_COOKIES_FILE = "C:\path\to\youtube_cookies.txt"
```

Полезные инструкции yt-dlp:

- [How do I pass cookies to yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
- [Exporting YouTube cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)

## Spotify: треки и плейлисты

В поле `Spotify URL` можно вставить ссылку на отдельный трек или публичный
плейлист.

- для трека приложение получает название и исполнителя через Spotify oEmbed,
  затем показывает несколько совпадений YouTube;
- для плейлиста приложение получает список треков через Spotify Web API,
  подбирает по одному лучшему совпадению YouTube для каждого трека и сохраняет
  исходный порядок в локальном плейлисте;
- найденные совпадения можно снять галочками перед скачиванием;
- исходные названия и исполнители Spotify сохраняются, даже если аудио скачано
  с YouTube.

Для чтения публичных плейлистов создай приложение в
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard) и задай
переменные в PowerShell из корня проекта:

```powershell
$env:SPOTIFY_CLIENT_ID = "your-client-id"
$env:SPOTIFY_CLIENT_SECRET = "your-client-secret"
```

После этого запускай приложение в том же окне PowerShell. Значения действуют
только для текущего окна и не сохраняются в Git. Приватные плейлисты требуют
пользовательскую OAuth-авторизацию и пока не поддерживаются.

## Локальная библиотека и удаление

Импортированные аудиофайлы копируются в `data/library/`.

Кнопка `Delete` удаляет одновременно:

- файл, если он существует;
- запись трека из базы;
- связанные записи взаимодействий.

Если файл уже отсутствует, запись трека всё равно удаляется из базы.

## Диагностика

### `ModuleNotFoundError: No module named 'app'`

Запускай команды из корня проекта и используй модульный запуск:

```powershell
uv run python -m app.desktop
uv run python -m pytest -q
```

### `Could not load libtorchcodec`

Проверь, что установлен shared FFmpeg и команда `ffmpeg -version` работает в
том же терминале, из которого запускается приложение.

### Нет `CUDAExecutionProvider`

Проверь, что установлен `onnxruntime-gpu`, а не только CPU-пакет:

```powershell
uv sync --locked
uv run python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

### YouTube просит войти или подтверждает, что пользователь не бот

Обнови Firefox cookies или экспортируй свежий файл в
`data/youtube_cookies.txt`. Не добавляй cookies в Git.

## Текущий статус ML-части

Уже готово:

- загрузка и ресэмплинг аудио в 16 кГц;
- окна по 30 секунд с перекрытием 15 секунд;
- MAEST ONNX inference;
- использование CUDA через ONNX Runtime;
- score threshold и учёт ранга;
- разделение полного названия на родительский жанр и поджанр;
- массовый reanalysis всех локальных треков из UI;
- автоматический анализ жанров после локального и YouTube-импорта;
- демонстрационный notebook.

Следующий этап — подключить автоматическое определение жанров к импорту
треков и сохранять жанровые признаки для рекомендательной модели.
