"""API 路由 — 系统配置管理"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.models.user import User
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/config", tags=["管理员-系统配置"])

# .env 文件路径（与 config 共享）
try:
    ENV_FILE = Path(settings.model_config.get("env_file", ".env")).resolve()
except Exception:
    ENV_FILE = Path("/app/.env")


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


class ModelConfigOut(BaseModel):
    """模型配置（用于前端展示）"""
    llm_provider: str = Field(default="DeepSeek", description="LLM 提供商")
    llm_model: str = ""
    llm_base_url: str = ""

    vl_provider: str = Field(default="DashScope/Aliyun", description="视觉模型提供商")
    vl_model: str = ""
    vl_base_url: str = ""

    embed_provider: str = Field(default="Ollama", description="嵌入服务提供商")
    embed_model: str = ""
    embed_base_url: str = ""


class ModelConfigUpdate(BaseModel):
    llm_model: str | None = Field(None, max_length=128)
    llm_base_url: str | None = Field(None, max_length=256)
    vl_model: str | None = Field(None, max_length=128)
    vl_base_url: str | None = Field(None, max_length=256)


@router.get("", response_model=ModelConfigOut)
async def get_config(_admin: User = Depends(require_admin)):
    """获取当前模型配置"""
    return ModelConfigOut(
        llm_provider="DeepSeek",
        llm_model=settings.llm_model or "deepseek-v4-flash",
        llm_base_url=settings.deepseek_base_url or "https://api.deepseek.com/v1",
        vl_provider="DashScope/Aliyun",
        vl_model=settings.dashscope_vision_model or "qwen3-vl-flash",
        vl_base_url=settings.dashscope_base_url or "https://dashscope.aliyuncs.com/api/v1",
        embed_provider="Ollama (bge-m3)",
        embed_model="bge-m3",
        embed_base_url=settings.ollama_base_url or "http://172.22.224.1:11434",
    )


@router.put("", response_model=ModelConfigOut)
async def update_config(
    data: ModelConfigUpdate,
    _admin: User = Depends(require_admin),
):
    """更新模型配置（写入 .env 文件并更新当前进程配置）"""
    try:
        # 读取当前 .env
        env_lines = []
        if ENV_FILE.exists():
            env_lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)

        # 要更新的键值对
        updates = {}
        if data.llm_model is not None:
            updates["LLM_MODEL"] = data.llm_model
            settings.llm_model = data.llm_model
        if data.llm_base_url is not None:
            updates["DEEPSEEK_BASE_URL"] = data.llm_base_url
            settings.deepseek_base_url = data.llm_base_url
        if data.vl_model is not None:
            updates["DASHSCOPE_VISION_MODEL"] = data.vl_model
            settings.dashscope_vision_model = data.vl_model
        if data.vl_base_url is not None:
            updates["DASHSCOPE_BASE_URL"] = data.vl_base_url
            settings.dashscope_base_url = data.vl_base_url

        # 更新 .env 文件（替换或追加）
        updated_keys = set()
        new_lines = []
        for line in env_lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # 追加不存在的键
        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        ENV_FILE.write_text("".join(new_lines), encoding="utf-8")
        logger.info(f"配置已更新: {updates}")

        return await get_config(_admin=_admin)
    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        raise HTTPException(status_code=500, detail=f"配置更新失败: {str(e)}")
