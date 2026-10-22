FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[server,neo4j]"
EXPOSE 8000
CMD ["uam-serve", "--host", "0.0.0.0", "--port", "8000"]
