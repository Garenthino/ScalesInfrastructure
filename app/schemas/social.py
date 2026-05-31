"""Pydantic schemas for singer social features (follows)."""
from pydantic import BaseModel, ConfigDict


class ScalesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FollowCreate(ScalesModel):
    followee_id: str


class FollowOut(ScalesModel):
    id: str
    venue_id: str
    follower_id: str
    followee_id: str
    followee_name: str  # hydrated from Singer.stage_name
    created_at: str


class FollowStatusOut(ScalesModel):
    is_following: bool
    follower_count: int
    following_count: int
    created_at: str | None = None
