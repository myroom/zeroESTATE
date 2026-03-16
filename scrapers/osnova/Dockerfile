FROM python:3.12-slim

WORKDIR /app

COPY scrapers/osnova/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY scrapers/base_scraper.py /app/scrapers/base_scraper.py
COPY scrapers/osnova/ /app/scrapers/osnova/

CMD ["python", "-m", "scrapers.osnova.scraper"]
