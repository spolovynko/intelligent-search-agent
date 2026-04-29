FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
        tesseract-ocr-nld \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY intelligent_search_agent ./intelligent_search_agent
COPY scripts ./scripts
COPY sql ./sql
COPY README.md .

RUN mkdir -p /app/storage/assets

EXPOSE 8000

CMD ["uvicorn", "intelligent_search_agent.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
