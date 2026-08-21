from __future__ import annotations

from pydantic import BaseModel, Field

from .espocrm_schema import EspoEntitySchema, EspoSchemaReader


class MappingCandidate(BaseModel):
    purpose: str
    matched_field: str | None = None
    confidence: str = "missing"
    candidates_checked: list[str] = Field(default_factory=list)


class EspoMappingRecommendation(BaseModel):
    entity_type: str
    matched: int
    missing: int
    mappings: list[MappingCandidate]


PURPOSE_ALIASES: dict[str, tuple[str, ...]] = {
    "lead_name": ("name",),
    "email": ("emailAddress", "email", "emailAddressData"),
    "phone": ("phoneNumber", "phone", "phoneNumberData"),
    "source": ("source", "leadSource", "sourceName", "cSource"),
    "assigned_user": ("assignedUserId", "assignedUser"),
    "status": ("status",),
    "project_interest": (
        "projectInterest",
        "interestedProject",
        "project",
        "cProjectInterest",
        "cInterestedProject",
        "duAnQuanTam",
    ),
    "budget": ("budget", "budgetAmount", "cBudget", "nganSach"),
    "intent": ("intent", "leadIntent", "cIntent", "mucDoQuanTam"),
    "last_contact": ("lastContactAt", "lastContactDate", "cLastContactAt", "lastActivityDate"),
    "modified_at": ("modifiedAt",),
}


def recommend_mapping(schema: EspoEntitySchema) -> EspoMappingRecommendation:
    by_exact = {field.name: field for field in schema.fields}
    by_folded = {field.name.casefold(): field for field in schema.fields}
    mappings: list[MappingCandidate] = []

    for purpose, aliases in PURPOSE_ALIASES.items():
        matched = None
        confidence = "missing"
        for alias in aliases:
            if alias in by_exact:
                matched = alias
                confidence = "exact"
                break
        if matched is None:
            for alias in aliases:
                field = by_folded.get(alias.casefold())
                if field is not None:
                    matched = field.name
                    confidence = "case_insensitive"
                    break
        mappings.append(
            MappingCandidate(
                purpose=purpose,
                matched_field=matched,
                confidence=confidence,
                candidates_checked=list(aliases),
            )
        )

    matched_count = sum(1 for item in mappings if item.matched_field)
    return EspoMappingRecommendation(
        entity_type=schema.entity_type,
        matched=matched_count,
        missing=len(mappings) - matched_count,
        mappings=mappings,
    )


class EspoMappingReader:
    def __init__(self, schema_reader: EspoSchemaReader | None = None) -> None:
        self.schema_reader = schema_reader or EspoSchemaReader()

    async def recommend(self, entity_type: str = "Lead") -> EspoMappingRecommendation:
        schema = await self.schema_reader.read_entity(entity_type)
        return recommend_mapping(schema)
