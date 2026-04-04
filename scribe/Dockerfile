FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        pandoc \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ /app/shared/
COPY scribe/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scribe/app.py .

EXPOSE 6003
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "6003"]
