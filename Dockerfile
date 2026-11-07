FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /code
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m appuser
COPY app ./app
COPY scripts ./scripts
RUN mkdir /code/appdata && chown -R appuser:appuser /code/appdata
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
