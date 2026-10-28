# Two-stage build: compile the frontend, then serve it from the FastAPI backend.
# NOTE: written for convenience; it was NOT built or tested in the development environment
# (Docker was not installed there). See README "Docker".
FROM node:20-bookworm-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /app/frontend/dist /app/frontend/dist
ENV GRIDWATCH_FRONTEND_DIST=/app/frontend/dist \
    GRIDWATCH_DATA_DIR=/app/data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "gridwatch.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
