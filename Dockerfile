FROM python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache .

EXPOSE 31555

CMD ["python", "main.py"]
