"""Базовый класс скрапера. Все скраперы наследуют от него."""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from croniter import croniter
from sqlalchemy.orm import Session

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import init_db_sync, SyncSessionLocal
from shared.models import Source, Property, PropertySnapshot, ScraperConfig, ScraperRun

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


class BaseScraper(ABC):
    """Базовый скрапер с логикой расписания и записи в БД."""

    slug: str = ""
    name: str = ""
    base_url: str = ""

    def __init__(self):
        self.logger = logging.getLogger(self.slug)
        init_db_sync()
        self._ensure_source()

    def _ensure_source(self):
        """Создать запись источника если нет."""
        with SyncSessionLocal() as session:
            source = session.query(Source).filter_by(slug=self.slug).first()
            if not source:
                source = Source(slug=self.slug, name=self.name, base_url=self.base_url)
                session.add(source)
                session.flush()
                config = ScraperConfig(source_id=source.id)
                session.add(config)
                session.commit()
                self.logger.info(f"Source '{self.slug}' created with id={source.id}")
            self.source_id = source.id

    @abstractmethod
    def scrape(self) -> list[dict]:
        """Собрать данные. Вернуть список словарей с полями PropertySnapshot."""
        ...

    def run_once(self):
        """Один запуск скрапера: собрать данные и записать в БД."""
        with SyncSessionLocal() as session:
            run = ScraperRun(source_id=self.source_id)
            session.add(run)
            session.commit()
            run_id = run.id

        try:
            self.logger.info("Starting scrape...")
            items = self.scrape()
            self.logger.info(f"Scraped {len(items)} items")
            stats = self._save_items(items)
            self._finish_run(run_id, "success", stats)
            self.logger.info(f"Done: {stats}")
        except Exception as e:
            self.logger.exception(f"Scrape failed: {e}")
            self._finish_run(run_id, "error", error=str(e))

    def _save_items(self, items: list[dict]) -> dict:
        """Сохранить собранные объекты в БД."""
        stats = {"scraped": len(items), "new": 0, "updated": 0, "removed": 0}
        now = datetime.utcnow()
        seen_external_ids = set()

        with SyncSessionLocal() as session:
            for item in items:
                external_id = str(item.get("external_id", ""))
                if not external_id:
                    continue
                seen_external_ids.add(external_id)

                # Найти или создать Property
                prop = session.query(Property).filter_by(
                    source_id=self.source_id, external_id=external_id
                ).first()

                if prop is None:
                    prop = Property(
                        source_id=self.source_id,
                        external_id=external_id,
                        first_seen=now,
                        last_seen=now,
                        is_active=True,
                    )
                    session.add(prop)
                    session.flush()
                    stats["new"] += 1
                else:
                    prop.last_seen = now
                    prop.is_active = True
                    stats["updated"] += 1

                # Создать снимок
                snapshot = PropertySnapshot(
                    property_id=prop.id,
                    source_id=self.source_id,
                    scraped_at=now,
                    project_name=item.get("project_name", ""),
                    project_url=item.get("project_url", ""),
                    title=item.get("title", ""),
                    property_url=item.get("property_url", ""),
                    property_type=item.get("property_type", ""),
                    status=item.get("status", ""),
                    address=item.get("address", ""),
                    district=item.get("district", ""),
                    metro_station=item.get("metro_station", ""),
                    metro_distance_min=item.get("metro_distance_min"),
                    latitude=item.get("latitude"),
                    longitude=item.get("longitude"),
                    area=item.get("area"),
                    price=item.get("price", ""),
                    price_value=item.get("price_value"),
                    price_per_sqm=item.get("price_per_sqm"),
                    floor=item.get("floor"),
                    floor_total=item.get("floor_total"),
                    ceiling_height=item.get("ceiling_height"),
                    finishing=item.get("finishing", ""),
                    has_finishing=item.get("has_finishing"),
                    completion_date=item.get("completion_date", ""),
                    image_url=item.get("image_url", ""),
                    images=json.dumps(item.get("images", []), ensure_ascii=False),
                    raw_data=json.dumps(item.get("raw_data", {}), ensure_ascii=False, default=str),
                )
                session.add(snapshot)

            # Пометить не найденные объекты как неактивные
            active_props = session.query(Property).filter_by(
                source_id=self.source_id, is_active=True
            ).all()
            for prop in active_props:
                if prop.external_id not in seen_external_ids:
                    prop.is_active = False
                    stats["removed"] += 1

            session.commit()

        return stats

    def _finish_run(self, run_id: int, status: str, stats: Optional[dict] = None, error: str = ""):
        with SyncSessionLocal() as session:
            run = session.query(ScraperRun).get(run_id)
            if run:
                run.finished_at = datetime.utcnow()
                run.status = status
                if stats:
                    run.items_scraped = stats.get("scraped", 0)
                    run.items_new = stats.get("new", 0)
                    run.items_updated = stats.get("updated", 0)
                    run.items_removed = stats.get("removed", 0)
                run.error_message = error
                session.commit()

            # Обновить last_run_at в config
            config = session.query(ScraperConfig).filter_by(source_id=self.source_id).first()
            if config:
                config.last_run_at = datetime.utcnow()
                if config.cron_expression:
                    cron = croniter(config.cron_expression, datetime.utcnow())
                    config.next_run_at = cron.get_next(datetime)
                session.commit()

    def loop(self):
        """Главный цикл: проверять расписание и запускать скрапер."""
        self.logger.info(f"Scraper '{self.slug}' started, entering schedule loop")

        while True:
            try:
                with SyncSessionLocal() as session:
                    config = session.query(ScraperConfig).filter_by(source_id=self.source_id).first()

                if config and config.enabled:
                    now = datetime.utcnow()
                    should_run = False

                    if config.next_run_at is None:
                        should_run = True
                    elif now >= config.next_run_at:
                        should_run = True

                    if should_run:
                        self.run_once()
                else:
                    self.logger.debug("Scraper disabled, sleeping...")

            except Exception as e:
                self.logger.exception(f"Loop error: {e}")

            time.sleep(60)  # Проверять каждую минуту
