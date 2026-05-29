"""
auth.py — HMRA Monitor
Gestion de l'authentification : JWT, bcrypt, dépendances FastAPI.
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from config import SECRET_KEY, TOKEN_EXPIRE_MINUTES

# ── Constantes ────────────────────────────────────────────────────────────────

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Hachage des mots de passe ─────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Retourne le hash bcrypt d'un mot de passe en clair."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe en clair correspond au hash stocké."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Tokens JWT ────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Génère un token JWT signé.
    Le payload contient au minimum : sub (username), role, service.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Décode et valide un token JWT.
    Lève une HTTPException 401 si invalide ou expiré.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ── Dépendances FastAPI ───────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Dépendance injectable dans n'importe quelle route.
    Retourne le payload du token : {sub, role, service, exp}.
    """
    return decode_token(token)


async def require_superadmin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dépendance qui interdit l'accès aux non-superadmin.
    """
    if current_user.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé au superadmin",
        )
    return current_user