# Musefy: аудит и план ML-ranking

Дата аудита: 2026-09-06  
Статус: архитектурное решение, без реализации ML

## 1. Решение

Musefy развиваем как гибридную систему:

```text
существующие recommenders
        ↓
candidate pool
        ↓
ML ranker в shadow/fallback-режиме
        ↓
diversity, cooldown и safety rules
        ↓
очередь рекомендаций
```

Текущая логика остаётся baseline и fallback. Новая модель не должна ломать рабочее приложение.

`SAVE` не входит в новую ML-логику. Новые события `SAVE` не собираем; старые записи этого типа считаем legacy и не используем как обучающий сигнал.

## 2. Что уже есть в проекте

### Домен и хранение

- `Interaction` хранит пользовательские события и время события.
- `RecommendationImpression` хранит трек, режим, позицию, score, время показа и session ID.
- SQLite хранит tracks, interactions и recommendation impressions.
- У `Recommendation` уже есть компоненты `mood_similarity`, `embedding_similarity` и `popularity_score`, но они сейчас не сохраняются внутри impression.

Основные точки: `app/domain/models.py`, `app/storage/models.py`, `app/storage/repository.py`.

### Генерация рекомендаций

`RecommendationService` выбирает recommender по `RecommendationContext`. Сейчас есть контексты:

- mood;
- genre;
- My Wave;
- track radio;
- popularity.

В mood-рекомендере действительно используется формула `0.45 / 0.40 / 0.15`, но popularity-рекомендер считает score иначе. Поэтому baseline должен быть не одной формулой, а фактической текущей логикой каждого контекста.

### Аналитика

`RecommendationAnalyticsService` уже умеет:

- записывать impressions;
- связывать последующие события с impression в окне атрибуции;
- считать completion rate и skip rate;
- считать ограниченные `recall@10`, `NDCG@10` и artist diversity.

Эти метрики пока описывают наблюдавшийся порядок рекомендаций, а не честный counterfactual-сравнитель двух моделей.

## 3. Фактические данные на момент аудита

Источник: `data/music.db`.

| Показатель | Значение | Вывод |
|---|---:|---|
| Пользователи | 3 | активность есть только у одного пользователя |
| Треки | 540 | библиотека достаточно большая для content features |
| Треки с embedding | 540 | embedding-признаки доступны для всей библиотеки |
| Треки с mood valence/arousal | 540 | базовые mood features доступны |
| Треки с mood profiles | 109 | этот feature нельзя считать обязательным |
| Взаимодействия | 413 | большая часть — telemetry, а не labels |
| Impressions | 210 | записаны за короткий период |
| Recommendation sessions | 7 | есть группировка по сессиям |
| Связанные сессией interactions | 18 из 413 | attribution пока слабый |
| Период interactions | 2026-08-29 — 2026-09-06 | меньше двух недель |
| Период impressions | 2026-09-05 — 2026-09-06 | около двух дней |

Распределение impressions: mood — 90, My Wave — 60, genre — 30, track radio — 30.

Для будущей ML-логики сейчас наблюдаются 88 потенциально положительных событий и 8 отрицательных ранних/явных skip-событий. Это недостаточно для уверенного production-обучения и особенно мало для честного temporal test. Реальные данные пока годятся для проверки пайплайна и Logistic Regression как учебного эксперимента. Для устойчивых сравнений понадобится synthetic режим или накопление истории.

## 4. Временный ML data contract

Одна строка датасета — один recommendation impression:

```text
features = состояние пользователя и трека на момент shown_at
label    = результат в течение attribution window после shown_at
```

### Признаки

Первая версия должна содержать небольшой набор числовых features:

- mood similarity;
- embedding similarity;
- baseline score;
- artist affinity;
- genre affinity;
- число предыдущих прослушиваний трека;
- число предыдущих ранних skip;
- число предыдущих positive-событий;
- давность последнего прослушивания;
- position в recommendation batch;
- mode/context рекомендации.

`artist` и `genre` не следует сразу превращать в огромный one-hot: для одного активного пользователя это легко приведёт к переобучению. На первом этапе лучше использовать агрегированные affinity-признаки.

### Labels v1

- positive: `LIKE`, `PLAYED_30S`, `COMPLETED_80`, `REPEAT`;
- negative: `SKIP_UNDER_30S`, явный `SKIP`, `DISLIKE`, `DO_NOT_RECOMMEND`;
- `PLAY`, `PLAY_START`, `SEEK` — telemetry, сами по себе label не создают;
- отсутствие реакции — `unknown`, не отрицательный пример;
- `SAVE` — исключён.

Для одного impression нужно сводить несколько событий к одному outcome по фиксированному правилу приоритетов. Attribution window должна быть ограниченной и одинаковой для train, validation, test и offline-метрик.

## 5. Защита от leakage

Для impression с временем `t` признаки истории могут использовать только события строго раньше `t`.

Нельзя при построении features учитывать будущие like, skip, completion или repeat. Это особенно важно для счётчиков, artist/genre affinity и similarity к истории пользователя.

Предпочтительный вариант — сохранять feature snapshot вместе с impression. Это надёжнее, чем пытаться спустя недели воспроизвести состояние recommender’а, особенно если менялись cooldown, half-life, embeddings или правила exploration.

Разбиение выполняется по времени impression:

```text
старые impressions  → train
следующие            → validation
самые новые          → test
```

Scaler, encoder и другие preprocessing artifacts обучаются только на train. Случайное перемешивание строк запрещено: один и тот же пользователь и трек могут встречаться в разные моменты, поэтому random split переносит информацию из будущего в прошлое.

## 6. Ограничения текущего логирования

1. Сейчас impression фиксирует элементы рекомендации, но не полный candidate pool. Поэтому offline-оценка видит только показанные треки и не знает, что модель сделала бы с непоказанными кандидатами.

2. Запись происходит при заполнении recommendation list. Это ближе к «показано в UI», но для будущей интеграции нужно отдельно различать generated, queued, displayed и started.

3. Только 18 interactions имеют `recommendation_session_id`. События без session ID нельзя безоговорочно считать реакцией на рекомендацию: пользователь мог запустить этот трек вручную.

4. Текущие `recall@10` и `NDCG@10` рассчитываются по уже записанному порядку impression batch. Их нельзя использовать как единственное доказательство, что новый ranker лучше.

## 7. Минимальные новые модули

Новые компоненты лучше расположить в `app/ml/ranking/`:

- `features.py` — построение features и их snapshot;
- `labels.py` — attribution и правила labels;
- `dataset.py` — temporal Dataset Builder;
- `evaluation.py` — единый offline evaluator;
- `artifacts.py` — model и preprocessing metadata;
- `inference.py` — безопасное ML reranking с fallback.

Не переписываем существующие `app/recommenders/*`. Сначала добавляем слой рядом с ними.

## 8. Следующий шаг

Следующий небольшой технический шаг — зафиксировать schema первого feature snapshot и написать тесты на temporal boundary:

- событие до `shown_at` попадает в features;
- событие ровно после `shown_at` не попадает;
- будущее событие может использоваться только для label;
- `SAVE` не появляется ни в features, ни в labels.

До прохождения этих тестов обучение модели не начинаем.
