FROM python:3.12-slim
WORKDIR /app
COPY scrapers/donstroy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY scrapers/base_scraper.py scrapers/base_scraper.py
COPY scrapers/donstroy/ scrapers/donstroy/
CMD ["python", "-m", "scrapers.donstroy.scraper"]
