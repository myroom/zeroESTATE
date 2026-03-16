# zeroESTATE

Система сбора и аналитики коммерческой недвижимости Москвы от топ-застройщиков.

## Что делает

- Ежедневно собирает данные о коммерческих помещениях с сайтов 12 застройщиков
- Хранит историю цен для отслеживания динамики
- Показывает аналитику и рейтинг ликвидности на дашборде

## Застройщики

| Застройщик | Метод | Объектов |
|-----------|-------|----------|
| ФСК | REST API | ~107 |
| ПИК | REST API | ~60 |
| Группа ЛСР | Playwright | ~166 |
| Гранель | REST API | ~34 |
| А101 | Playwright | ~173 |
| Level Group | Playwright | ~31 |
| ГК ОСНОВА | REST API | ~17 |
| Брусника | Playwright | ~68 |
| Донстрой | REST API | ~2 |
| Самолёт | Playwright | нужен прокси |
| MR Group | Playwright | нужен прокси |
| Seven Suns | Playwright | нужен прокси |

## Стек

- **Backend**: Python 3.12, FastAPI, SQLAlchemy
- **Frontend**: Jinja2 + HTMX + TailwindCSS + Chart.js
- **Скрапинг**: Playwright (SPA), requests (REST API)
- **БД**: PostgreSQL 16
- **Инфраструктура**: Docker Compose (14 контейнеров)

## Запуск

```bash
docker compose up --build
```

Дашборд: http://localhost:8080

## Структура

```
zeroESTATE/
├── docker-compose.yml
├── shared/              # Модели БД, конфиг
├── scrapers/            # 12 скраперов (каждый в отдельном контейнере)
│   ├── base_scraper.py  # Базовый класс с расписанием и записью в БД
│   ├── browser_scraper.py # Базовый Playwright-скрапер
│   ├── pik/             # REST API
│   ├── fsk/             # REST API
│   ├── a101/            # Playwright
│   └── ...
└── dashboard/           # FastAPI дашборд
    ├── routers/         # API + страницы
    └── templates/       # Jinja2 шаблоны
```
