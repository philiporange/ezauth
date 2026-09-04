"""Signing key management, authenticated with an application secret key.

Rotation is the response to a suspected key compromise and to routine key
hygiene. Rotating adds a new active key and retires the current one, which
keeps verifying until it is dropped, so tokens issued moments before the
rotation are not invalidated. Dropping retired keys is the second step, run
once every token signed by them has expired; it is what actually stops a
leaked key from being usable.
"""

from fastapi import APIRouter

from ezauth.dependencies import DbSession, SecretKeyApp
from ezauth.services import keys as key_service

router = APIRouter()


@router.get("/keys")
async def list_keys(db: DbSession, app: SecretKeyApp):
    """List the application's signing keys, newest active key first."""
    app_keys = await key_service.verification_keys(db, app)
    return {
        "keys": [
            {
                "kid": k.kid,
                "is_active": k.is_active,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "retired_at": k.retired_at.isoformat() if k.retired_at else None,
            }
            for k in app_keys
        ]
    }


@router.post("/keys/rotate")
async def rotate(db: DbSession, app: SecretKeyApp):
    """Issue a new signing key and retire the current one."""
    new_key = await key_service.rotate_key(db, app)
    return {"kid": new_key.kid, "status": "rotated"}


@router.delete("/keys/retired")
async def drop_retired(db: DbSession, app: SecretKeyApp):
    """Stop accepting signatures from every retired key."""
    removed = await key_service.drop_retired_keys(db, app)
    return {"removed": removed}
