from pydantic import BaseModel, ConfigDict, Field

_MODEL = ConfigDict(extra="ignore", populate_by_name=True)


class NoticeLinkItem(BaseModel):
    model_config = _MODEL

    title: str = ""
    url: str = ""
    date: str = ""


class EventNoticeItem(BaseModel):
    model_config = _MODEL

    title: str = ""
    url: str = ""
    thumbnailUrl: str = ""
    startDate: str = ""
    endDate: str = ""


class CashshopNoticeItem(BaseModel):
    model_config = _MODEL

    title: str = ""
    url: str = ""
    thumbnailUrl: str = ""
    startDate: str = ""
    endDate: str = ""
    ongoing: bool = False


class NoticesResponse(BaseModel):
    model_config = _MODEL

    notice: list[NoticeLinkItem] = Field(default_factory=list)
    update: list[NoticeLinkItem] = Field(default_factory=list)
    event: list[EventNoticeItem] = Field(default_factory=list)
    cashshop: list[CashshopNoticeItem] = Field(default_factory=list)
