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
    min_area: Optional[str] = Query(None),
    max_area: Optional[str] = Query(None),
    min_price: Optional[str] = Query(None),
    max_price: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    metro: Optional[str] = Query(None),
    sort: str = Query("price_per_sqm"),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
):
    # Convert empty strings to None, parse numbers
    def _float(v):
        if not v or not v.strip():
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def _int(v):
        if not v or not v.strip():
            return None
        try:
            return int(v)
        except ValueError:
            return None

    min_area_f = _float(min_area)
    max_area_f = _float(max_area)
    min_price_i = _int(min_price)
    max_price_i = _int(max_price)
    source = source if source else None
    property_type = property_type if property_type else None
    district = district if district and district.strip() else None
    metro = metro if metro and metro.strip() else None
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
        # Match all raw types that map to this normalized type
        from sqlalchemy import or_
        TYPE_NORMALIZE_FILTER = {
            "Коммерческое": ["коммерческое"],
            "Ритейл": ["ритейл"],
            "Торговое": ["торговое", "Торговое"],
            "Офис": ["офис", "офисный центр", "Офисное"],
            "Офис продаж": ["sales_office", "check_in_office"],
            "Свободного назначения": ["свободного назначения", "Свободного назначения"],
        }
        raw_types_for_filter = TYPE_NORMALIZE_FILTER.get(property_type)
        if raw_types_for_filter:
            query = query.where(snap.property_type.in_(raw_types_for_filter))
        else:
            query = query.where(snap.property_type == property_type)
    if min_area_f is not None:
        query = query.where(snap.area >= min_area_f)
    if max_area_f is not None:
        query = query.where(snap.area <= max_area_f)
    if min_price_i is not None:
        query = query.where(snap.price_value >= min_price_i)
    if max_price_i is not None:
        query = query.where(snap.price_value <= max_price_i)
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

    # Get distinct property types (normalized)
    TYPE_NORMALIZE = {
        "коммерческое": "Коммерческое",
        "ритейл": "Ритейл",
        "торговое": "Торговое",
        "Торговое": "Торговое",
        "офис": "Офис",
        "офисный центр": "Офис",
        "Офисное": "Офис",
        "sales_office": "Офис продаж",
        "check_in_office": "Офис продаж",
        "свободного назначения": "Свободного назначения",
    }
    types_q = await db.execute(
        select(PropertySnapshot.property_type)
        .where(PropertySnapshot.property_type != "")
        .distinct()
    )
    raw_types = [r[0] for r in types_q.all()]
    normalized = sorted(set(TYPE_NORMALIZE.get(t, t.capitalize()) for t in raw_types))
    property_types = normalized

    # Build reverse map: normalized type -> list of raw types
    type_reverse = {}
    for raw_t in raw_types:
        norm = TYPE_NORMALIZE.get(raw_t, raw_t.capitalize())
        type_reverse.setdefault(norm, []).append(raw_t)

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
        "filters_clean": {
            "min_area": min_area_f,
            "max_area": max_area_f,
            "min_price": min_price_i,
            "max_price": max_price_i,
        },
        "sort": sort,
        "order": order,
        "current_page": "properties",
    }

    # If HTMX request, return only the table partial
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/properties_table.html", ctx)

    return templates.TemplateResponse("pages/properties.html", ctx)
