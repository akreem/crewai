FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

COPY shared/ /app/shared/
COPY watchman/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watchman/app.py .

EXPOSE 6001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "6001"]
