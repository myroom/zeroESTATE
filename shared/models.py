from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Text, DateTime,
    Boolean, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Source(Base):
    """Застройщик / источник данных."""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)  # pik, samolet, ...
    name = Column(String(200), nullable=False)               # ПИК, Самолёт, ...
    base_url = Column(String(500), nullable=False)
    logo_url = Column(String(500), default="")

    properties = relationship("Property", back_populates="source")
    scraper_config = relationship("ScraperConfig", back_populates="source", uselist=False)
    scraper_runs = relationship("ScraperRun", back_populates="source")


class Property(Base):
    """Уникальный коммерческий объект (дедупликация по source + external_id)."""
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external"),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    external_id = Column(String(200), nullable=False)  # ID объекта на сайте застройщика
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    source = relationship("Source", back_populates="properties")
    snapshots = relationship("PropertySnapshot", back_populates="property", order_by="PropertySnapshot.scraped_at.desc()")


class PropertySnapshot(Base):
    """Ежедневный снимок данных объекта."""
    __tablename__ = "property_snapshots"
    __table_args__ = (
        Index("ix_snapshots_property_date", "property_id", "scraped_at"),
        Index("ix_snapshots_source_date", "source_id", "scraped_at"),
    )

    id = Column(BigInteger, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Проект / ЖК
    project_name = Column(String(300), default="")        # Название ЖК
    project_url = Column(String(500), default="")

    # Объект
    title = Column(String(500), default="")                # Название/номер помещения
    property_url = Column(String(500), default="")         # Ссылка на объект
    property_type = Column(String(100), default="")        # офис, торговое, св. назначение
    status = Column(String(100), default="")               # в продаже, бронь, ...

    # Адрес и локация
    address = Column(String(500), default="")
    district = Column(String(200), default="")             # Район
    metro_station = Column(String(200), default="")
    metro_distance_min = Column(Integer, nullable=True)    # Минуты пешком до метро
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Площадь
    area = Column(Float, nullable=True)                    # Общая площадь м²

    # Цена
    price = Column(String(100), default="")                # "по запросу" или число как строка
    price_value = Column(BigInteger, nullable=True)        # Числовое значение цены (руб)
    price_per_sqm = Column(BigInteger, nullable=True)      # Цена за м²

    # Этаж
    floor = Column(Integer, nullable=True)
    floor_total = Column(Integer, nullable=True)

    # Характеристики
    ceiling_height = Column(Float, nullable=True)          # Высота потолков
    finishing = Column(String(200), default="")            # Отделка
    has_finishing = Column(Boolean, nullable=True)

    # Сроки
    completion_date = Column(String(200), default="")      # Срок сдачи

    # Медиа
    image_url = Column(String(500), default="")            # Главное фото
    images = Column(Text, default="")                      # JSON-список URL фото

    # Дополнительные данные (JSON)
    raw_data = Column(Text, default="")                    # Полный JSON от источника

    property = relationship("Property", back_populates="snapshots")


class ScraperConfig(Base):
    """Конфигурация расписания скрапера."""
    __tablename__ = "scraper_config"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    cron_expression = Column(String(100), default="0 6 * * *")  # По умолчанию 6:00 утра
    proxy_url = Column(String(500), default="")
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)

    source = relationship("Source", back_populates="scraper_config")


class ScraperRun(Base):
    """Лог запусков скрапера."""
    __tablename__ = "scraper_runs"
    __table_args__ = (
        Index("ix_runs_source_started", "source_id", "started_at"),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="running")  # running, success, error
    items_scraped = Column(Integer, default=0)
    items_new = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    items_removed = Column(Integer, default=0)
    error_message = Column(Text, default="")

    source = relationship("Source", back_populates="scraper_runs")
