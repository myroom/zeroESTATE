from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import init_db, get_async_session
from shared.models import Source, ScraperConfig

from dashboard.routers import overview, properties, property_detail, analytics, scrapers

SOURCES_SEED = [
    {"slug": "pik", "name": "ПИК", "base_url": "https://www.pik.ru"},
    {"slug": "samolet", "name": "Самолёт", "base_url": "https://samolet.ru"},
    {"slug": "mrgroup", "name": "MR Group", "base_url": "https://www.mr-group.ru"},
    {"slug": "fsk", "name": "ФСК", "base_url": "https://www.fsk.ru"},
    {"slug": "a101", "name": "А101", "base_url": "https://www.a101.ru"},
    {"slug": "donstroy", "name": "Донстрой", "base_url": "https://www.donstroy.com"},
    {"slug": "level", "name": "Level Group", "base_url": "https://levelgroup.ru"},
    {"slug": "granelle", "name": "Гранель", "base_url": "https://granelle.ru"},
    {"slug": "sevensuns", "name": "Seven Suns", "base_url": "https://sevensuns.ru"},
    {"slug": "brusnika", "name": "Брусника", "base_url": "https://moskva.brusnika.ru"},
    {"slug": "osnova", "name": "ГК ОСНОВА", "base_url": "https://gk-osnova.ru"},
    {"slug": "lsr", "name": "Группа ЛСР", "base_url": "https://www.lsr.ru"},
    {"slug": "trade_estate", "name": "Основа Trade Estate", "base_url": "https://trade-estate.ru"},
]


async def seed_sources():
    async with get_async_session()() as session:
        result = await session.execute(select(Source))
        existing = {s.slug for s in result.scalars().all()}

        for src in SOURCES_SEED:
            if src["slug"] not in existing:
                source = Source(**src)
                session.add(source)

        await session.commit()

        # Seed default ScraperConfig for each source
        result = await session.execute(select(Source))
        sources = result.scalars().all()

        result_cfg = await session.execute(select(ScraperConfig))
        existing_configs = {c.source_id for c in result_cfg.scalars().all()}

        for source in sources:
            if source.id not in existing_configs:
                cfg = ScraperConfig(
                    source_id=source.id,
                    enabled=True,
                    cron_expression="0 5 * * *",
                )
                session.add(cfg)

        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_sources()
    yield


app = FastAPI(title="zeroESTATE Dashboard", lifespan=lifespan)

app.include_router(overview.router)
app.include_router(properties.router)
app.include_router(property_detail.router)
app.include_router(analytics.router)
app.include_router(scrapers.router)

import pathlib

_base = pathlib.Path(__file__).resolve().parent
static_dir = _base / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(_base / "templates"))
