FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system -e .

COPY . .

RUN mkdir -p logs

EXPOSE 8000

CMD ["python", "app.py"]
