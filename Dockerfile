FROM python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv && uv pip install --system --no-cache -i https://mirrors.aliyun.com/pypi/simple/ .

EXPOSE 31555

CMD ["python", "main.py"]
