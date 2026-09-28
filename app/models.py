from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class Season(Base):
    __tablename__ = "seasons"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    start = Column(Date, nullable=False)  # first day of the first month
    base_stake = Column(Float, nullable=False, default=50.0)
    max_bets = Column(Integer, nullable=False, default=2)
    active = Column(Boolean, nullable=False, default=True)


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    active = Column(Boolean, nullable=False, default=True)


class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    month = Column(Integer, nullable=False)  # 0 = first month of the season
    stake = Column(Float, nullable=False)
    description = Column(Text, nullable=False, default="")
    odds = Column(String(30), nullable=True)
    result = Column(String(10), nullable=False, default="pending")  # pending/won/lost
    collect = Column(Float, nullable=False, default=0.0)
    bonus = Column(Boolean, nullable=False, default=False)  # bookmaker bonus bet, not paid from stake
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    member = relationship("Member")
