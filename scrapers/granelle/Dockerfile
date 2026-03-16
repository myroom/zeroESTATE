FROM python:3.12-slim
WORKDIR /app
COPY scrapers/granelle/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY scrapers/__init__.py scrapers/__init__.py
COPY scrapers/base_scraper.py scrapers/base_scraper.py
COPY scrapers/granelle/ scrapers/granelle/
CMD ["python", "-m", "scrapers.granelle.scraper"]
