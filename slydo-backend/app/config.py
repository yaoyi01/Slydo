"""Slydo 配置"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-flash"

    # Ollama
    ollama_base_url: str = "http://172.22.224.1:11434"
    ollama_vision_model: str = "qwen3-vl-fast:8b"

    # DashScope (阿里云视觉)
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_vision_model: str = "qwen3-vl-plus"

    # PostgreSQL
    database_url: str = ""

    # Qdrant
    qdrant_path: str = str(Path.home() / ".slydo" / "qdrant")
    qdrant_url: str = "http://127.0.0.1:6333"

    # LLM Wiki
    slydo_wiki_path: str = str(Path.home() / ".slydo" / "wiki")

    # 应用
    app_name: str = "Slydo"
    debug: bool = False

    # 并发控制
    upload_concurrency: int = 2  # 同时最多处理 N 个文件的上传（含去重+写盘）
    upload_queue_timeout: int = 600  # 上传排队超时秒数（大文件多时可调大）
    ingest_concurrency: int = 2  # 同时最多允许 N 个入库任务（磁盘密集操作，LibreOffice/pdf2image等）

    # JWT
    jwt_secret_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
