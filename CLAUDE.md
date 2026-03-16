# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Обзор

**zeroESTATE** — система сбора и аналитики коммерческой недвижимости от московских застройщиков. Грабит данные с 7 сайтов раз в день, хранит историю цен, показывает аналитику для выбора ликвидных помещений.

## Архитектура

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  PostgreSQL  │◄────│  Dashboard (FastAPI + Jinja2 + HTMX)        │
│   :5433      │     │  :8080 — аналитика, управление расписанием  │
└──────┬───────┘     └──────────────────────────────────────────────┘
       │
       ├──── scraper-pik      (requests, REST API)
       ├──── scraper-samolet  (Playwright)
       ├──── scraper-mrgroup  (Playwright)
       ├──── scraper-fsk      (Playwright)
       ├──── scraper-a101     (Playwright)
       ├──── scraper-donstroy (Playwright)
       └──── scraper-level    (Playwright)
```

Каждый скрапер — отдельный Docker-контейнер. Расписание хранится в БД (таблица `scraper_config`), управляется из дашборда.

## Стек

- **Backend**: Python 3.12, FastAPI, SQLAlchemy (async для дашборда, sync для скраперов)
- **Frontend**: Jinja2 + HTMX + TailwindCSS CDN + Chart.js
- **Скрапинг**: Playwright (SPA-сайты), requests (PIK API)
- **БД**: PostgreSQL 16 (Docker)
- **Деплой**: Docker Compose

## Команды

```bash
# Запуск всего стека
docker compose up --build

# Только БД и дашборд (без скраперов)
docker compose up db dashboard

# Один скрапер
docker compose up db scraper-pik

# Пересобрать конкретный контейнер
docker compose build scraper-pik && docker compose up scraper-pik
```

## Структура

```
zeroESTATE/
├── docker-compose.yml
├── shared/                  # Общий код (копируется в каждый контейнер)
│   ├── models.py            # SQLAlchemy модели (Source, Property, PropertySnapshot, ...)
│   ├── db.py                # Engine/session (async + sync)
│   └── config.py            # DATABASE_URL из env
├── scrapers/
│   ├── base_scraper.py      # Базовый класс: расписание, запись в БД, loop()
│   ├── browser_scraper.py   # Базовый Playwright-скрапер
│   ├── pik/                 # REST API скрапер
│   ├── samolet/             # Playwright
│   ├── mrgroup/             # Playwright (антибот)
│   ├── fsk/                 # Playwright (Nuxt)
│   ├── a101/                # Playwright (Nuxt 3)
│   ├── donstroy/            # Playwright (Bitrix)
│   └── level/               # Playwright (React SPA)
└── dashboard/
    ├── main.py              # FastAPI app, seed данных
    ├── routers/             # overview, properties, analytics, scrapers
    ├── templates/           # Jinja2 (base.html + pages/)
    └── static/
```

## БД — ключевые таблицы

- `sources` — застройщики (pik, samolet, ...)
- `properties` — уникальные объекты (source_id + external_id)
- `property_snapshots` — ежедневные снимки всех данных объекта (цена, площадь, статус, ...)
- `scraper_config` — расписание и прокси для каждого скрапера
- `scraper_runs` — лог запусков

## Как добавить новый скрапер

1. Создать `scrapers/{slug}/scraper.py` — наследовать от `BrowserScraper` или `BaseScraper`
2. Задать `slug`, `name`, `base_url`
3. Реализовать `scrape()` или `scrape_with_browser()` — вернуть `list[dict]` с полями PropertySnapshot
4. Создать `Dockerfile` и `requirements.txt`
5. Добавить сервис в `docker-compose.yml`
6. Добавить seed-данные в `dashboard/main.py`

## Прокси

Прокси настраивается через дашборд (таблица `scraper_config.proxy_url`) для каждого скрапера отдельно.

## Порты

- PostgreSQL: 5433 (хост) → 5432 (контейнер)
- Dashboard: 8080
