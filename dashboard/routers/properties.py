import math
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.db import get_db
from shared.models import Source, Property, PropertySnapshot

import pathlib

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))

PAGE_SIZE = 50


@router.get("/properties")
async def properties_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    source: Optional[str] = Query(None),
    property_type: Optional[str] = Query(None),
    min_area: Optional[float] = Query(None),
    max_area: Optional[float] = Query(None),
    min_price: Optional[int] = Query(None),
    max_price: Optional[int] = Query(None),
    district: Optional[str] = Query(None),
    metro: Optional[str] = Query(None),
    sort: str = Query("price_per_sqm"),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
):
    # Subquery: latest snapshot per property
    latest_snap = (
        select(
            PropertySnapshot.property_id,
            func.max(PropertySnapshot.id).label("max_snap_id"),
        )
        .group_by(PropertySnapshot.property_id)
        .subquery()
    )

    snap = aliased(PropertySnapshot)

    # Base query: active properties joined with latest snapshot
    query = (
        select(Property, snap, Source)
        .join(latest_snap, Property.id == latest_snap.c.property_id)
        .join(snap, snap.id == latest_snap.c.max_snap_id)
        .join(Source, Property.source_id == Source.id)
        .where(Property.is_active == True)
    )

    # Filters
    if source:
        query = query.where(Source.slug == source)
    if property_type:
        query = query.where(snap.property_type == property_type)
    if min_area is not None:
        query = query.where(snap.area >= min_area)
    if max_area is not None:
        query = query.where(snap.area <= max_area)
    if min_price is not None:
        query = query.where(snap.price_value >= min_price)
    if max_price is not None:
        query = query.where(snap.price_value <= max_price)
    if district:
        query = query.where(snap.district.ilike(f"%{district}%"))
    if metro:
        query = query.where(snap.metro_station.ilike(f"%{metro}%"))

    # Count total for pagination
    count_q = select(func.count()).select_from(query.subquery())
    total_count_r = await db.execute(count_q)
    total_count = total_count_r.scalar() or 0
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))

    # Sort
    sort_map = {
        "price": snap.price_value,
        "area": snap.area,
        "price_per_sqm": snap.price_per_sqm,
        "floor": snap.floor,
    }
    sort_col = sort_map.get(sort, snap.price_per_sqm)
    if order == "desc":
        query = query.order_by(desc(sort_col).nulls_last())
    else:
        query = query.order_by(asc(sort_col).nulls_last())

    query = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    result = await db.execute(query)
    rows = result.all()

    # Get available sources for filter
    sources_q = await db.execute(select(Source).order_by(Source.name))
    all_sources = sources_q.scalars().all()

    # Get distinct property types
    types_q = await db.execute(
        select(PropertySnapshot.property_type)
        .where(PropertySnapshot.property_type != "")
        .distinct()
    )
    property_types = [r[0] for r in types_q.all()]

    items = []
    for prop, snapshot, src in rows:
        items.append({
            "property": prop,
            "snapshot": snapshot,
            "source": src,
        })

    ctx = {
        "request": request,
        "items": items,
        "all_sources": all_sources,
        "property_types": property_types,
        "total_count": total_count,
        "total_pages": total_pages,
        "page": page,
        "filters": {
            "source": source or "",
            "property_type": property_type or "",
            "min_area": min_area or "",
            "max_area": max_area or "",
            "min_price": min_price or "",
            "max_price": max_price or "",
            "district": district or "",
            "metro": metro or "",
        },
        "sort": sort,
        "order": order,
        "current_page": "properties",
    }

    # If HTMX request, return only the table partial
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/properties_table.html", ctx)

    return templates.TemplateResponse("pages/properties.html", ctx)
