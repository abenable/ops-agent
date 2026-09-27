FROM python:3.13-slim
RUN pip install --no-cache-dir prometheus-client==0.22.1
COPY app.py /app.py
CMD ["python", "-u", "/app.py"]
