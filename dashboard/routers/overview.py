from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.models import Source, Property, PropertySnapshot, ScraperRun

import pathlib

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))

# Метод сбора данных для каждого скрапера
SCRAPER_METHODS = {
    "pik": "REST API",
    "fsk": "REST API",
    "donstroy": "REST API",
    "granelle": "REST API",
    "osnova": "REST API",
    "a101": "Playwright",
    "level": "Playwright",
    "lsr": "Playwright",
    "brusnika": "Playwright",
    "samolet": "Playwright (нужен прокси)",
    "mrgroup": "Playwright (нужен прокси)",
    "sevensuns": "Playwright (нужен прокси)",
}


@router.get("/")
async def overview(request: Request, db: AsyncSession = Depends(get_db)):
    # Total properties and active
    total_q = await db.execute(select(func.count(Property.id)))
    total_properties = total_q.scalar() or 0

    active_q = await db.execute(select(func.count(Property.id)).where(Property.is_active == True))
    total_active = active_q.scalar() or 0

    # New today / removed today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    new_today_q = await db.execute(
        select(func.count(Property.id)).where(Property.first_seen >= today_start)
    )
    new_today = new_today_q.scalar() or 0

    removed_today_q = await db.execute(
        select(func.count(Property.id)).where(
            and_(Property.is_active == False, Property.last_seen >= today_start)
        )
    )
    removed_today = removed_today_q.scalar() or 0

    # Sources with stats
    sources_q = await db.execute(select(Source))
    sources = sources_q.scalars().all()

    source_stats = []
    for src in sources:
        # Active properties count
        active_cnt_q = await db.execute(
            select(func.count(Property.id)).where(
                and_(Property.source_id == src.id, Property.is_active == True)
            )
        )
        active_cnt = active_cnt_q.scalar() or 0

        # Average price per sqm (from latest snapshots)
        avg_price_q = await db.execute(
            select(func.avg(PropertySnapshot.price_per_sqm)).where(
                and_(
                    PropertySnapshot.source_id == src.id,
                    PropertySnapshot.price_per_sqm.isnot(None),
                    PropertySnapshot.scraped_at >= today_start - timedelta(days=1),
                )
            )
        )
        avg_price = avg_price_q.scalar()

        # Last run
        last_run_q = await db.execute(
            select(ScraperRun)
            .where(ScraperRun.source_id == src.id)
            .order_by(ScraperRun.started_at.desc())
            .limit(1)
        )
        last_run = last_run_q.scalar()

        source_stats.append({
            "source": src,
            "active_count": active_cnt,
            "avg_price_sqm": int(avg_price) if avg_price else None,
            "last_run_at": last_run.started_at if last_run else None,
            "last_run_status": last_run.status if last_run else None,
            "method": SCRAPER_METHODS.get(src.slug, "—"),
        })

    return templates.TemplateResponse("pages/overview.html", {
        "request": request,
        "total_properties": total_properties,
        "total_active": total_active,
        "new_today": new_today,
        "removed_today": removed_today,
        "source_stats": source_stats,
        "current_page": "overview",
    })
