"""
Database Schemas for ClassCom

Each Pydantic model typically maps to a MongoDB collection with the
lowercased class name as the collection name.

Collections used:
- student
- subject
- presentation
- message
- meta (key/value for app-wide flags)
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Student(BaseModel):
    roll_number: str = Field(..., description="Unique roll number")
    name: Optional[str] = Field(None, description="Student full name")
    is_admin: bool = Field(False, description="Admin flag")
    is_active: bool = Field(True, description="Active flag")
    notifications_read_at: Optional[datetime] = Field(None, description="Timestamp of last seen notifications")


class Subject(BaseModel):
    code: str = Field(..., description="Subject code (e.g., CS101)")
    acronym: str = Field(..., description="Short code used in tabs (e.g., CS)")
    title: str = Field(..., description="Subject title")
    syllabus: Optional[List[str]] = Field(default_factory=list, description="Bullet list of syllabus entries")


class Presentation(BaseModel):
    subject_code: str = Field(..., description="Subject code")
    subject_acronym: str = Field(..., description="Subject acronym for mapping")
    topic: str = Field(..., description="Topic title")
    assigned_to: Optional[str] = Field(None, description="Roll number of assigned student")
    due_date: Optional[datetime] = Field(None, description="Due date/time")
    status: str = Field("upcoming", description="upcoming | completed | revoked")
    submission_link: Optional[str] = Field(None, description="Google Form link for PPT submission")


class Message(BaseModel):
    type: str = Field("message", description="message | alert")
    title: str = Field(..., description="Short title")
    body: str = Field(..., description="Message contents")
    created_by: Optional[str] = Field(None, description="Roll number of creator if any (admin)")


class Meta(BaseModel):
    key: str
    value: str
