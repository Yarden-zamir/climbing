from typing import List, Optional
from pydantic import BaseModel


class NewPerson(BaseModel):
    name: str
    skills: List[str] = []
    location: List[str] = []
    achievements: List[str] = []
    temp_image_path: Optional[str] = None


class LearnedItems(BaseModel):
    """Skills and achievements a crew member gained during a specific album."""

    name: str
    skills: List[str] = []
    achievements: List[str] = []


class AlbumSubmission(BaseModel):
    url: str
    crew: List[str]
    # Optional album location (free text, e.g., "Kalymnos, Greece")
    location: Optional[str] = None
    new_people: Optional[List[NewPerson]] = []
    learned: List[LearnedItems] = []


class AlbumCrewEdit(BaseModel):
    album_url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []
    learned: List[LearnedItems] = []


class AddSkillsRequest(BaseModel):
    crew_name: str
    skills: List[str]


class AddAchievementsRequest(BaseModel):
    crew_name: str
    achievements: List[str] 


class AlbumMetadataUpdate(BaseModel):
    album_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    cover_image: Optional[str] = None
    location: Optional[str] = None
