from typing import Literal, Optional

from pydantic import BaseModel

Confidence = Literal["high", "medium", "low"]


class ExtractedCaptureItem(BaseModel):
    person_name: Optional[str] = None
    title: Optional[str] = None
    company_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    allotted_initials: Optional[str] = None   # the handwritten circled code, if any
    note: Optional[str] = None                # any other handwritten annotation
    confidence: Confidence


class CaptureExtractionResult(BaseModel):
    items: list[ExtractedCaptureItem]
