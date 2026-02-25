from fastapi import APIRouter

from ezauth.dependencies import AppDep, RedisDep
from ezauth.schemas.hashcash import ChallengeResponse
from ezauth.services.hashcash import create_challenge

router = APIRouter()


@router.post("/challenges", response_model=ChallengeResponse)
async def request_challenge(
    app: AppDep,
    redis: RedisDep,
):
    result = await create_challenge(redis)
    return ChallengeResponse(**result)
