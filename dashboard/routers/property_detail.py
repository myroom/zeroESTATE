from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.models import Property, PropertySnapshot, Source

import pathlib

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))


@router.get("/properties/{property_id}")
async def property_detail(
    request: Request,
    property_id: int,
    db: AsyncSession = Depends(get_db),
):
    prop_q = await db.execute(
        select(Property, Source)
        .join(Source, Property.source_id == Source.id)
        .where(Property.id == property_id)
    )
    row = prop_q.first()
    if not row:
        return templates.TemplateResponse("pages/404.html", {
            "request": request, "current_page": "properties",
        }, status_code=404)

    prop, source = row

    # All snapshots ordered by date
    snaps_q = await db.execute(
        select(PropertySnapshot)
        .where(PropertySnapshot.property_id == property_id)
        .order_by(PropertySnapshot.scraped_at.asc())
    )
    snapshots = snaps_q.scalars().all()

    latest = snapshots[-1] if snapshots else None

    return templates.TemplateResponse("pages/property_detail.html", {
        "request": request,
        "property": prop,
        "source": source,
        "latest": latest,
        "snapshots": snapshots,
        "current_page": "properties",
    })


@router.get("/api/properties/{property_id}/price-history")
async def price_history(property_id: int, db: AsyncSession = Depends(get_db)):
    snaps_q = await db.execute(
        select(PropertySnapshot)
        .where(PropertySnapshot.property_id == property_id)
        .order_by(PropertySnapshot.scraped_at.asc())
    )
    snapshots = snaps_q.scalars().all()

    labels = [s.scraped_at.strftime("%d.%m.%Y") for s in snapshots]
    prices = [s.price_value for s in snapshots]
    prices_sqm = [s.price_per_sqm for s in snapshots]

    return JSONResponse({
        "labels": labels,
        "prices": prices,
        "prices_sqm": prices_sqm,
    })
