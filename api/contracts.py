"""核心 API 的稳定输入契约。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class GenerateCopyRequest(ApiModel):
    materials: dict[str, Any] = Field(default_factory=dict)
    selected_books: list[str] = Field(default_factory=list)
    source_copy: str = ""
    generation_mode: Literal["fresh", "rewrite"] = "fresh"
    narrative_mode: Literal["default", "parallelism", "six-stage", "contrast-first"] = "default"
    project_id: str = ""
    locked_paragraphs: list[Any] = Field(default_factory=list)
    book_support_mode: Literal["integrated", "off"] = "integrated"
    book_quote_strategy: Literal["restrained", "standard", "amplified"] = "standard"
    creator_framework_version: Literal["yzk_v1"] = "yzk_v1"
    target_length_mode: Literal["auto", "manual"] = "auto"
    target_length: Optional[int] = Field(default=None, ge=300, le=3000)
    active_dna_ids: list[int] = Field(default_factory=list)
    generation_id: str = ""

    def service_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"generation_id"})


class TextPayload(ApiModel):
    text: str = Field(min_length=1, max_length=50000)


class DialogueSessionRequest(ApiModel):
    mode: Literal["mirror", "book"] = "mirror"
    persona_id: str = ""
    title: str = Field(default="", max_length=80)


class DialogueSessionPatch(ApiModel):
    title: Optional[str] = Field(default=None, max_length=80)
    pinned: Optional[bool] = None


class DialogueSessionBulkDeleteRequest(ApiModel):
    session_ids: list[str] = Field(default_factory=list, max_length=200)
    permanent: bool = False


class DialogueMessageRequest(ApiModel):
    message: str = Field(default="", max_length=12000)
    retry_message_id: str = ""
    use_search: bool = False

    @model_validator(mode="after")
    def message_or_retry(self):
        if not self.message and not self.retry_message_id:
            raise ValueError("请输入对话内容")
        return self


class DialogueFeedbackRequest(ApiModel):
    action: Literal["like_self", "unlike_self", "remember", "forget"]
    note: str = Field(default="", max_length=1000)


class DialogueExtractRequest(ApiModel):
    target: Literal["material", "persona_asset"] = "material"
    text: str = Field(min_length=1, max_length=12000)
    asset_type: str = "voice_rule"
    title: str = Field(default="", max_length=80)
    project_id: str = ""
    source: str = "dialogue"
    material_group: str = "insight"


class StylePublishRequest(ApiModel):
    force: bool = False
    reason: str = Field(default="", max_length=500)


class StyleFeedbackRequest(ApiModel):
    project_id: str = ""
    style_version: str = ""
    decision: Literal["keep", "revise"]
    feedback: str = Field(default="", max_length=2000)
    copy_snapshot: str = Field(default="", max_length=20000)
