"""初始化默认管理员账号"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import async_session_factory
from app.models.user import User
from app.utils.auth import hash_password

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123456"


ALL_PERMISSIONS = ["upload", "users", "files", "dashboard", "usage", "config"]

async def ensure_admin():
    """确保默认管理员账号存在"""
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.username == DEFAULT_ADMIN_USERNAME)
            )
            if result.scalar_one_or_none():
                logger.info("管理员账号已存在，跳过初始化")
                return

            admin = User(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                display_name="系统管理员",
                role="admin",
                permissions=ALL_PERMISSIONS,
                token_ttl_hours=168,
            )
            session.add(admin)
            await session.commit()
            logger.info(f"默认管理员账号已创建: {DEFAULT_ADMIN_USERNAME}")
    except Exception as e:
        logger.warning(f"创建管理员账号失败（可能首次启动表还未创建）: {e}")
