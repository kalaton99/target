"""Auth REST endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from . import service
from core.security import current_user_id

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(req: RegisterRequest):
    return await service.register(req.email, req.username, req.password)


@router.post("/login")
async def login(req: LoginRequest):
    return await service.login(req.email, req.password)


@router.get("/me")
async def me(user_id: str = Depends(current_user_id)):
    user = await service.get_me(user_id)
    if not user:
        raise HTTPException(404, "USER_NOT_FOUND")
    return user
