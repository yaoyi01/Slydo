"""Qdrant 向量数据库连接管理"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams

from app.config import settings


# 全局 Qdrant 客户端（单例）
qdrant_client: QdrantClient | None = None

COLLECTION_NAME = "slides"
VECTOR_SIZE = 1024  # BGE-M3 维度


def get_qdrant() -> QdrantClient:
    """获取 Qdrant 客户端（单例）

    优先级：
        1. QDRANT_URL 环境变量（服务器模式，推荐）
        2. settings.qdrant_url 配置（服务器模式）
        3. settings.qdrant_path 配置（本地文件模式，回退）
    """
    global qdrant_client
    if qdrant_client is None:
        qdrant_url = os.environ.get("QDRANT_URL", "") or getattr(settings, "qdrant_url", "")
        if qdrant_url:
            qdrant_client = QdrantClient(
                url=qdrant_url,
                prefer_grpc=False,
                timeout=10,
            )
        else:
            qdrant_path = Path(settings.qdrant_path).expanduser()
            qdrant_path.mkdir(parents=True, exist_ok=True)
            qdrant_client = QdrantClient(path=str(qdrant_path))
    return qdrant_client


async def init_qdrant():
    """初始化 Qdrant collection（不存在时创建）"""
    client = get_qdrant()
    collections = client.get_collections().collections
    existing = {c.name for c in collections}

    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )
        # 创建 payload 索引加速过滤（仅 Qdrant 服务端有效，本地模式忽略）
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="deck_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # 本地模式不支持 payload index
        print(f"[Qdrant] 创建 collection '{COLLECTION_NAME}' 完成")
    else:
        print(f"[Qdrant] collection '{COLLECTION_NAME}' 已存在")


async def check_qdrant() -> dict:
    """健康检查：测试 Qdrant 连接"""
    try:
        client = get_qdrant()
        info = client.get_collections()
        return {"connected": True, "collections": [c.name for c in info.collections]}
    except Exception as e:
        return {"connected": False, "error": str(e)}
