FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:server", "--reload", "--host", "0.0.0.0", "--port", "8000"]