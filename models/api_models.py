from typing import List, Optional
from pydantic import BaseModel


class NewPerson(BaseModel):
    name: str
    skills: List[str] = []
    location: List[str] = []
    achievements: List[str] = []
    temp_image_path: Optional[str] = None


class AlbumSubmission(BaseModel):
    url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class AlbumCrewEdit(BaseModel):
    album_url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class AddSkillsRequest(BaseModel):
    crew_name: str
    skills: List[str]


class AddAchievementsRequest(BaseModel):
    crew_name: str
    achievements: List[str] 
