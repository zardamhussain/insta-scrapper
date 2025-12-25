FROM python:3.12-slim

WORKDIR /app

COPY main.py .

RUN pip install --no-cache-dir flask requests

EXPOSE 3400

CMD ["python", "main.py"]