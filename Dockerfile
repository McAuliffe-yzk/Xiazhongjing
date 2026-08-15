FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8860 \
    XIANGZHONGJING_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt \
    && useradd --create-home --uid 10001 xiangzhongjing \
    && mkdir -p /data \
    && chown -R xiangzhongjing:xiangzhongjing /data

COPY --chown=xiangzhongjing:xiangzhongjing . ./

USER xiangzhongjing
EXPOSE 8860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8860/api/xiangzhongjing/health', timeout=3)" || exit 1

CMD ["python", "main.py"]
