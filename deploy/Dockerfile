FROM python:3.11-slim

# 换 apt 源为阿里云
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 阿里云源
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

COPY slydo-backend/pyproject.toml ./
RUN pip install --no-cache-dir "setuptools>=75.0" \
    "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" \
    "asyncpg>=0.30.0" "sqlalchemy[asyncio]>=2.0" \
    "qdrant-client>=1.12.0" "httpx>=0.28.0" \
    "pydantic>=2.0" "pydantic-settings>=2.0" \
    "python-multipart>=0.0.18" \
    "passlib[bcrypt]>=1.7.4" "pyjwt>=2.9.0" "bcrypt<4.2" \
    "python-pptx>=1.0.0" "Pillow>=11.0.0"

COPY slydo-backend/ ./

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
