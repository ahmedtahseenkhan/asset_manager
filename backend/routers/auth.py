from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import timedelta

from backend.database import get_db
from backend.models.user import User
from backend.schemas.user import UserCreate, UserOut, UserLogin
from backend.schemas.common import APIResponse
from backend.utils.security import verify_password, get_password_hash, create_access_token
from backend.middleware.auth import get_current_user
from backend.services.audit_service import AuditService
from backend.config import settings
from backend.utils.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=dict)
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        await AuditService.log(db, request, None, "auth.login_failed",
                               resource_type="auth",
                               detail={"username": form_data.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await AuditService.log(db, request, user, "auth.login",
                           resource_type="auth", resource_id=user.username)

    access_token_expires = timedelta(minutes=settings.jwt_expiry_minutes)
    access_token = create_access_token(
        subject=user.username, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/register", response_model=APIResponse[UserOut])
async def register(request: Request, user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    from backend.licensing.enforcement import check_user_limit
    await check_user_limit(db)

    result = await db.execute(select(User).where((User.username == user_in.username) | (User.email == user_in.email)))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await AuditService.log(db, request, user, "user.created",
                           resource_type="user", resource_id=user.username,
                           detail={"role": user.role})
    return APIResponse(data=user, message="Registration successful")

@router.get("/me", response_model=APIResponse[UserOut])
async def get_me(current_user: User = Depends(get_current_user)):
    return APIResponse(data=current_user)
