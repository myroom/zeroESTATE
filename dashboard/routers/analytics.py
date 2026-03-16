from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.models import Source, Property, PropertySnapshot

import pathlib

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))


@router.get("/analytics")
async def analytics_page(request: Request):
    return templates.TemplateResponse("pages/analytics.html", {
        "request": request,
        "current_page": "analytics",
    })


@router.get("/api/analytics/avg-price-by-source")
async def avg_price_by_source(db: AsyncSession = Depends(get_db)):
    """Average price per m2 by source (for bar chart)."""
    query = (
        select(Source.name, func.avg(PropertySnapshot.price_per_sqm).label("avg_price"))
        .join(Source, PropertySnapshot.source_id == Source.id)
        .where(PropertySnapshot.price_per_sqm.isnot(None))
        .group_by(Source.name)
        .order_by(Source.name)
    )
    result = await db.execute(query)
    rows = result.all()

    return JSONResponse({
        "labels": [r[0] for r in rows],
        "values": [int(r[1]) if r[1] else 0 for r in rows],
    })


@router.get("/api/analytics/price-trend")
async def price_trend(db: AsyncSession = Depends(get_db)):
    """Price per m2 trend over time by source (last 30 days)."""
    since = datetime.utcnow() - timedelta(days=30)
    query = (
        select(
            cast(PropertySnapshot.scraped_at, Date).label("day"),
            Source.name,
            func.avg(PropertySnapshot.price_per_sqm).label("avg_price"),
        )
        .join(Source, PropertySnapshot.source_id == Source.id)
        .where(
            and_(
                PropertySnapshot.price_per_sqm.isnot(None),
                PropertySnapshot.scraped_at >= since,
            )
        )
        .group_by(cast(PropertySnapshot.scraped_at, Date), Source.name)
        .order_by(cast(PropertySnapshot.scraped_at, Date))
    )
    result = await db.execute(query)
    rows = result.all()

    # Group by source
    datasets = {}
    dates_set = set()
    for day, name, avg_price in rows:
        dates_set.add(day.isoformat())
        if name not in datasets:
            datasets[name] = {}
        datasets[name][day.isoformat()] = int(avg_price) if avg_price else 0

    dates = sorted(dates_set)
    series = []
    for name, vals in datasets.items():
        series.append({
            "label": name,
            "data": [vals.get(d, None) for d in dates],
        })

    return JSONResponse({"labels": dates, "datasets": series})


TYPE_NORMALIZE = {
    "коммерческое": "Коммерческое",
    "ритейл": "Ритейл",
    "торговое": "Торговое",
    "Торговое": "Торговое",
    "Торговое помещ.": "Торговое",
    "офис": "Офис",
    "офисный центр": "Офис",
    "Офисное": "Офис",
    "sales_office": "Офис продаж",
    "check_in_office": "Офис продаж",
    "свободного назначения": "Свободного назначения",
    "Свободного назначения": "Свободного назначения",
}


@router.get("/api/analytics/by-type")
async def by_type(db: AsyncSession = Depends(get_db)):
    """Property count by type (pie chart)."""
    latest = (
        select(
            PropertySnapshot.property_id,
            func.max(PropertySnapshot.id).label("max_id"),
        )
        .group_by(PropertySnapshot.property_id)
        .subquery()
    )
    query = (
        select(PropertySnapshot.property_type, func.count().label("cnt"))
        .join(latest, PropertySnapshot.id == latest.c.max_id)
        .join(Property, Property.id == PropertySnapshot.property_id)
        .where(and_(Property.is_active == True, PropertySnapshot.property_type != ""))
        .group_by(PropertySnapshot.property_type)
        .order_by(func.count().desc())
    )
    result = await db.execute(query)
    rows = result.all()

    # Normalize types
    merged = {}
    for raw_type, cnt in rows:
        normalized = TYPE_NORMALIZE.get(raw_type, raw_type.capitalize() if raw_type else "Другое")
        merged[normalized] = merged.get(normalized, 0) + cnt

    sorted_types = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    return JSONResponse({
        "labels": [t[0] for t in sorted_types],
        "values": [t[1] for t in sorted_types],
    })


@router.get("/api/analytics/by-district")
async def by_district(db: AsyncSession = Depends(get_db)):
    """Properties by district (bar chart)."""
    latest = (
        select(
            PropertySnapshot.property_id,
            func.max(PropertySnapshot.id).label("max_id"),
        )
        .group_by(PropertySnapshot.property_id)
        .subquery()
    )
    query = (
        select(PropertySnapshot.district, func.count().label("cnt"))
        .join(latest, PropertySnapshot.id == latest.c.max_id)
        .join(Property, Property.id == PropertySnapshot.property_id)
        .where(and_(Property.is_active == True, PropertySnapshot.district != ""))
        .group_by(PropertySnapshot.district)
        .order_by(func.count().desc())
        .limit(20)
    )
    result = await db.execute(query)
    rows = result.all()

    return JSONResponse({
        "labels": [r[0] for r in rows],
        "values": [r[1] for r in rows],
    })


@router.get("/api/analytics/by-metro")
async def by_metro(db: AsyncSession = Depends(get_db)):
    """Properties by metro station (bar chart)."""
    latest = (
        select(
            PropertySnapshot.property_id,
            func.max(PropertySnapshot.id).label("max_id"),
        )
        .group_by(PropertySnapshot.property_id)
        .subquery()
    )
    query = (
        select(PropertySnapshot.metro_station, func.count().label("cnt"))
        .join(latest, PropertySnapshot.id == latest.c.max_id)
        .join(Property, Property.id == PropertySnapshot.property_id)
        .where(and_(Property.is_active == True, PropertySnapshot.metro_station != ""))
        .group_by(PropertySnapshot.metro_station)
        .order_by(func.count().desc())
        .limit(20)
    )
    result = await db.execute(query)
    rows = result.all()

    # Clean metro names: strip \n and trailing distance info
    import re
    merged_metro = {}
    for raw_name, cnt in rows:
        clean = raw_name.split("\n")[0].strip() if raw_name else ""
        clean = re.sub(r'\s*\d+\s*мин\.?.*$', '', clean).strip()
        if not clean:
            continue
        merged_metro[clean] = merged_metro.get(clean, 0) + cnt

    sorted_metro = sorted(merged_metro.items(), key=lambda x: x[1], reverse=True)[:20]
    return JSONResponse({
        "labels": [m[0] for m in sorted_metro],
        "values": [m[1] for m in sorted_metro],
    })


@router.get("/api/analytics/new-removed-trend")
async def new_removed_trend(db: AsyncSession = Depends(get_db)):
    """New vs removed properties over time (last 30 days)."""
    since = datetime.utcnow() - timedelta(days=30)

    # New per day
    new_q = await db.execute(
        select(
            cast(Property.first_seen, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(Property.first_seen >= since)
        .group_by(cast(Property.first_seen, Date))
        .order_by(cast(Property.first_seen, Date))
    )
    new_rows = new_q.all()

    # Removed per day
    removed_q = await db.execute(
        select(
            cast(Property.last_seen, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(and_(Property.is_active == False, Property.last_seen >= since))
        .group_by(cast(Property.last_seen, Date))
        .order_by(cast(Property.last_seen, Date))
    )
    removed_rows = removed_q.all()

    dates_set = set()
    new_map = {}
    removed_map = {}
    for day, cnt in new_rows:
        d = day.isoformat()
        dates_set.add(d)
        new_map[d] = cnt
    for day, cnt in removed_rows:
        d = day.isoformat()
        dates_set.add(d)
        removed_map[d] = cnt

    dates = sorted(dates_set)
    return JSONResponse({
        "labels": dates,
        "new": [new_map.get(d, 0) for d in dates],
        "removed": [removed_map.get(d, 0) for d in dates],
    })


@router.get("/api/analytics/liquidity-scores")
async def liquidity_scores(db: AsyncSession = Depends(get_db)):
    """Liquidity analysis for properties.

    Scoring criteria:
    - Price per m2 below area average = potentially undervalued
    - Ground floor (floor=1) = most liquid for retail
    - Metro proximity < 10 min = more liquid
    - Area 50-200 m2 = most liquid commercial range
    """
    latest = (
        select(
            PropertySnapshot.property_id,
            func.max(PropertySnapshot.id).label("max_id"),
        )
        .group_by(PropertySnapshot.property_id)
        .subquery()
    )

    query = (
        select(
            PropertySnapshot.property_id,
            PropertySnapshot.project_name,
            PropertySnapshot.address,
            PropertySnapshot.property_type,
            PropertySnapshot.area,
            PropertySnapshot.price_value,
            PropertySnapshot.price_per_sqm,
            PropertySnapshot.floor,
            PropertySnapshot.metro_station,
            PropertySnapshot.metro_distance_min,
            PropertySnapshot.district,
            Source.name.label("source_name"),
        )
        .join(latest, PropertySnapshot.id == latest.c.max_id)
        .join(Property, Property.id == PropertySnapshot.property_id)
        .join(Source, PropertySnapshot.source_id == Source.id)
        .where(
            and_(
                Property.is_active == True,
                PropertySnapshot.price_per_sqm.isnot(None),
                PropertySnapshot.area.isnot(None),
            )
        )
    )
    result = await db.execute(query)
    rows = result.all()

    if not rows:
        return JSONResponse({"items": []})

    # Calculate overall average price per sqm
    avg_all = sum(r.price_per_sqm for r in rows if r.price_per_sqm) / max(1, len([r for r in rows if r.price_per_sqm]))

    # District averages
    district_prices = {}
    for r in rows:
        if r.district and r.price_per_sqm:
            district_prices.setdefault(r.district, []).append(r.price_per_sqm)
    district_avg = {d: sum(v) / len(v) for d, v in district_prices.items()}

    scored = []
    for r in rows:
        score = 0
        reasons = []

        # Below district/overall average price
        local_avg = district_avg.get(r.district, avg_all)
        if r.price_per_sqm and r.price_per_sqm < local_avg * 0.9:
            score += 2
            reasons.append("Цена ниже средней по району")
        elif r.price_per_sqm and r.price_per_sqm < local_avg:
            score += 1
            reasons.append("Цена ниже средней")

        # Ground floor
        if r.floor == 1:
            score += 2
            reasons.append("1 этаж (ритейл)")

        # Metro proximity
        if r.metro_distance_min and r.metro_distance_min <= 5:
            score += 2
            reasons.append("Метро < 5 мин")
        elif r.metro_distance_min and r.metro_distance_min <= 10:
            score += 1
            reasons.append("Метро < 10 мин")

        # Optimal area
        if r.area and 50 <= r.area <= 200:
            score += 2
            reasons.append("Оптимальная площадь 50-200 м\u00b2")
        elif r.area and 30 <= r.area <= 300:
            score += 1
            reasons.append("Приемлемая площадь")

        scored.append({
            "property_id": r.property_id,
            "project_name": r.project_name or "",
            "address": r.address or "",
            "source_name": r.source_name,
            "property_type": r.property_type or "",
            "area": r.area,
            "price_value": r.price_value,
            "price_per_sqm": r.price_per_sqm,
            "floor": r.floor,
            "metro_station": r.metro_station or "",
            "metro_distance_min": r.metro_distance_min,
            "district": r.district or "",
            "score": score,
            "reasons": reasons,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return JSONResponse({"items": scored[:50]})
