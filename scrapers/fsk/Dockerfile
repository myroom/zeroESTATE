FROM python:3.12-slim

WORKDIR /app

COPY scrapers/fsk/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY scrapers/base_scraper.py /app/scrapers/base_scraper.py
COPY scrapers/fsk/ /app/scrapers/fsk/

CMD ["python", "-m", "scrapers.fsk.scraper"]
