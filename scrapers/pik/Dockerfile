FROM python:3.12-slim

WORKDIR /app

COPY scrapers/pik/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY scrapers/__init__.py /app/scrapers/__init__.py
COPY scrapers/base_scraper.py /app/scrapers/base_scraper.py
COPY scrapers/browser_scraper.py /app/scrapers/browser_scraper.py
COPY scrapers/pik/ /app/scrapers/pik/

CMD ["python", "-m", "scrapers.pik.scraper"]
