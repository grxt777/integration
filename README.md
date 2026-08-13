# Bank Intelligence Platform

Единая платформа, объединяющая два проекта в одно приложение, одну базу PostgreSQL и один API:

| Источник | Модуль | Что даёт |
|---|---|---|
| [`dilshod544/kassa-`](https://github.com/dilshod544/kassa-) | **Cashier Intelligence** | Аналитика кассиров: KPI, нагрузка, БЭК/ФРОНТ, штат, отпуска, замещения, дисциплинарные взыскания |
| [`grxt777/arena-test`](https://github.com/grxt777/arena-test) | **ATM Monitor** | Реестр банкоматов и филиалов, остатки, карта, прогноз и маршруты инкассации |

---

## Что даёт объединение

* **Одна база вместо двух.** Домен ATM был на SQLite, кассиры — на PostgreSQL. Весь ATM-слой (`atms`, `branches`) портирован на PostgreSQL с UPSERT через `ON CONFLICT`, пулом соединений и общими транзакциями.
* **Одно приложение и один порт.** Раньше это были два независимых FastAPI-сервера с одинаковыми путями `/api/cashiers/*`, которые конфликтовали. Теперь — один `api/main.py` со сквозным набором эндпоинтов.
* **Один дашборд.** Общий хаб `/dashboard/index.html` с живыми показателями обоих модулей и перекрёстной навигацией между картой ATM и аналитикой кассиров.
* **Единый центр импорта.** `/dashboard/import.html` — выбор между реестром банкоматов, реестром филиалов и отчётами кассиров.
* **Сохранена «продвинутая» версия каждой фичи.** Там, где функциональность пересекалась, взят более развитый вариант — см. таблицу ниже.

### Как разрешены пересечения

| Фича | Решение |
|---|---|
| Аналитика кассиров | Взята модульная версия из `kassa-` (`core/cashier/`: helpers / parsers / repository / analytics) вместо однофайловой из `arena-test` — она умеет HR-статусы, замещения, филиалы, взыскания и фильтры |
| Импорт кассиров | Взят «Единый центр импорта» из `kassa-` (drag & drop, авто-определение типа файла) |
| База данных | PostgreSQL из `kassa-`; ATM-слой переписан с SQLite на PostgreSQL |
| Конфигурация | Объединена: DSN PostgreSQL + бизнес-пороги ATM (`LOW_CASH_PCT`, `DEFAULT_CAPACITY`, параметры маршрутов) |
| Главная страница | Написан новый общий хаб, объединяющий разделы обоих проектов |

### Исправления, сделанные при объединении

* **Долгота ATM терялась при импорте.** В реестре две колонки с одинаковым заголовком «Геолокация» (широта и долгота); вторая отбрасывалась как дубликат, из-за чего маршруты инкассации не строились. Теперь второе вхождение корректно трактуется как `lon`.
* **Кириллица в PostgreSQL.** Добавлены явные `client_encoding=UTF8` и создание БД с `ENCODING 'UTF8'` — без этого импорт узбекских/русских реестров падал с `UnicodeEncodeError` на серверах с локалью `SQL_ASCII`.
* **Жёстко зашитый `localhost:8000` во фронтенде.** Все страницы переведены на `location.origin` (и `wss://` для WebSocket), поэтому дашборд работает за обратным прокси и на любом домене.

---

## Быстрый старт

### Вариант 1 — Docker (рекомендуется)

```bash
docker compose up --build
```

Откройте <http://localhost:8000> — база поднимется и проинициализируется автоматически.

### Вариант 2 — локально

```bash
./run.sh
```

Больше ничего делать не нужно — скрипт сам:

1. установит зависимости Python;
2. запустит PostgreSQL (а на macOS с Homebrew при необходимости и установит его);
3. создаст роль `bank` и базу `bank_db` в кодировке UTF8;
4. освободит порт 8000, если его занял прошлый запуск;
5. поднимет сервер на `0.0.0.0:8000`.

Полезные переменные:

```bash
APP_PORT=8001 ./run.sh      # запустить на другом порту
SKIP_DB_SETUP=1 ./run.sh    # не трогать базу (например, она удалённая)
```

При необходимости скопируйте `.env.example` в `.env` и поправьте доступы к БД.
Настроить только базу, без запуска приложения: `./scripts/setup-postgres.sh`.

### Требования

* Python 3.9+
* PostgreSQL 14+ (сама база создаётся автоматически при первом старте, кодировка UTF8)

### Частые проблемы

| Симптом | Решение |
|---|---|
| `Connection refused ... port 5432` | Запустите через `./run.sh` — он поднимет PostgreSQL сам. Вручную: `brew services start postgresql@16` (macOS), `sudo systemctl start postgresql` (Linux) |
| `role "bank" does not exist` / ошибка пароля | `./scripts/setup-postgres.sh` |
| `Address already in use` | `./run.sh` сам освободит порт. Иначе: `lsof -ti:8000 \| xargs kill -9` или `APP_PORT=8001 ./run.sh` |
| Нет прав на `brew` / нет PostgreSQL | Поднимите всё в контейнерах: `docker compose up` |
| `Не удалось запустить PostgreSQL автоматически` + нет Homebrew | Самый быстрый путь — `docker compose up`. Либо поставьте [Homebrew](https://brew.sh) или [Postgres.app](https://postgresapp.com) |
| PostgreSQL установлен, но скрипт его не видит | Он ищет бинарники в `/opt/homebrew`, `/usr/local`, Postgres.app и `/Library/PostgreSQL`. Если у вас другой путь или порт — пропишите их в `.env` |

При проблемах с подключением приложение выводит понятное сообщение с текущими
настройками и командами для исправления — вместо стектрейса драйвера.

---

## Интерфейс

| Страница | Назначение |
|---|---|
| `/dashboard/index.html` | Главный хаб: сводные показатели и переход в оба модуля |
| `/dashboard/map.html` | Карта банкоматов с остатками и границами регионов |
| `/dashboard/analytics.html` | Аналитика сети ATM |
| `/dashboard/incassation.html` | Календарь прогнозных инкассаций |
| `/dashboard/cashiers.html` | Аналитика кассиров: KPI, рейтинги, статусы, фильтры |
| `/dashboard/cashier-detail.html` | Карточка кассира с детализацией операций |
| `/dashboard/import.html` | Центр импорта — выбор типа реестра |
| `/dashboard/import-atms.html` | Импорт реестра банкоматов |
| `/dashboard/import-branches.html` | Импорт реестра филиалов |
| `/dashboard/import-cashiers.html` | Импорт отчётов кассиров (KPI и штат) |
| `/docs` | Swagger UI |

---

## API

### Банкоматы

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/atms` | Список ATM с фильтрами по региону, филиалу, статусу |
| `GET` | `/api/atms/stats` | Статистика по областям и филиалам |
| `GET` | `/api/atms/{terminal_id}` | Детали банкомата |
| `GET` | `/api/atms/{terminal_id}/cassettes` | Кассеты по номиналам и рекомендация по загрузке |
| `POST` | `/api/atms/import` | Импорт XLSX-реестра (`?replace=true` — с очисткой) |
| `POST` | `/api/atms/import/clear` | Очистить реестр ATM |
| `POST` | `/api/atms/{terminal_id}/balance` | Обновить остаток |
| `POST` | `/api/atms/balances/bulk` | Массовое обновление остатков |
| `GET` | `/api/alerts` | Банкоматы в статусе critical/warning |
| `GET` | `/api/baseline` | Сводный отчёт по остаткам и регионам |

### Филиалы и инкассация

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/branches` | Список филиалов (фильтр `incassation=0/1`) |
| `GET` | `/api/branches/stats` | Статистика по филиалам |
| `GET` | `/api/branches/{local_code}` | Детали филиала |
| `POST` | `/api/branches/import` | Импорт XLSX-реестра филиалов |
| `POST` | `/api/branches/import/clear` | Очистить реестр филиалов |
| `POST` | `/api/routes/incassation` | Маршруты: филиал с признаком «Инкассация = 1» → ATM своего региона |
| `GET` | `/api/incassation/plan` | Прогнозный план выездов на `days` дней |

### Кассиры

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/api/cashiers/import` | Импорт отчёта KPI («Kassirlar bo'yicha», XLSX/CSV) |
| `POST` | `/api/cashiers/import-status` | Импорт реестра штата и статусов |
| `GET` | `/api/cashiers/analytics` | KPI, рейтинги, структура операций, фильтры по роли/статусу/филиалу/должности |
| `GET` | `/api/cashiers/{report_id}` | Углублённая аналитика одного кассира |

### Служебные

`GET /api/health`, `GET /uzbekistan.geojson`, `GET /uzbekistan_regional.geojson`, `GET /tashkent_districts.geojson`

---

## Структура проекта

```
api/
  main.py                  # единое FastAPI-приложение (оба домена)
  core/
    config.py              # DSN PostgreSQL + бизнес-пороги ATM
    db.py                  # пул соединений, схема, репозиторий ATM и филиалов
    importer.py            # парсер XLSX реестров ATM и филиалов
    incassation_router.py  # региональные маршруты инкассации
    cashier_analytics.py   # фасад совместимости для домена кассиров
    cashier/
      helpers.py           # нормализация строк, разбор HR-статусов
      parsers.py           # парсеры Excel: KPI и реестр штата
      repository.py        # схема и сохранение данных кассиров
      analytics.py         # расчёт нагрузки, БЭК/ФРОНТ, выборки
dashboard/                 # статические страницы обоих модулей
migrations/                # SQL-схема (000 — ATM/филиалы, 001 — кассиры)
scripts/setup-postgres.sh  # создание роли и базы в локальном PostgreSQL
tests/                     # pytest для аналитики кассиров
legacy/                    # исторические скрипты сбора данных по ATM
samples/                   # примеры Excel-файлов
```

## Тесты

```bash
pytest
```

CI (`.github/workflows/ci.yml`) поднимает PostgreSQL 16 и прогоняет тесты на каждый push и pull request.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Хост базы |
| `POSTGRES_PORT` | `5432` | Порт базы |
| `POSTGRES_DB` | `bank_db` | Имя базы |
| `POSTGRES_USER` | `bank` | Пользователь |
| `POSTGRES_PASSWORD` | `bank` | Пароль |
| `LOW_CASH_PCT` | `0.20` | Порог статуса critical |
| `WARNING_CASH_PCT` | `0.40` | Порог статуса warning |
| `DEFAULT_CAPACITY` | `400000000` | Ёмкость банкомата по умолчанию, UZS |
