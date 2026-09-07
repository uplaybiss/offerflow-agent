FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json ./
RUN corepack enable && pnpm install --frozen-lockfile=false
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist ./frontend/dist
ENV OFFERFLOW_DB_PATH=/data/offerflow.db OFFERFLOW_QUALITY_DB_PATH=/data/quality.db APP_TIMEZONE=Asia/Shanghai APP_HOST=0.0.0.0
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "app.py"]
