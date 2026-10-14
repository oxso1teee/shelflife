FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY LICENSE main.py ./
COPY bot ./bot

RUN useradd --system --uid 10001 --no-create-home shelflife
USER shelflife

CMD ["python", "main.py"]
