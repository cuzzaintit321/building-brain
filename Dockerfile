FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY static/ ./static/
RUN mkdir -p /app/data && useradd -u 10001 -r -m brain && chown -R brain:brain /app/data
USER brain
EXPOSE 8000
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]
