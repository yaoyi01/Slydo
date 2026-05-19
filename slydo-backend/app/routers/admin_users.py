"""API 路由 — 管理员用户管理"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.utils.auth import hash_password

router = APIRouter(prefix="/api/admin/users", tags=["管理员-用户管理"])


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员创建用户"""
    # 检查用户名唯一性
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        role=data.role,
        permissions=data.permissions or [],
        token_ttl_hours=data.token_ttl_hours or 168,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("", response_model=list[UserOut])
async def list_users(
    q: str = Query("", max_length=64),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员获取用户列表"""
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员更新用户（禁用/修改角色/重置密码）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if data.is_active is not None:
        user.is_active = data.is_active
    if data.role is not None:
        user.role = data.role
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    if data.permissions is not None:
        user.permissions = data.permissions
    if data.token_ttl_hours is not None:
        user.token_ttl_hours = data.token_ttl_hours

    # 创建时补上默认权限
    if user.permissions is None or user.permissions == []:
        if user.role == "admin":
            from app.init_admin import ALL_PERMISSIONS
            user.permissions = ALL_PERMISSIONS

    await db.flush()
    await db.refresh(user)
    return user
