from npd_agent_hub.espocrm_mapping import recommend_mapping
from npd_agent_hub.espocrm_schema import EspoEntitySchema, EspoFieldSchema


def test_recommend_mapping_matches_standard_and_custom_fields():
    schema = EspoEntitySchema(
        entity_type="Lead",
        field_count=8,
        fields=[
            EspoFieldSchema(name="name", type="varchar"),
            EspoFieldSchema(name="emailAddress", type="email"),
            EspoFieldSchema(name="phoneNumber", type="phone"),
            EspoFieldSchema(name="source", type="enum"),
            EspoFieldSchema(name="assignedUserId", type="id"),
            EspoFieldSchema(name="status", type="enum"),
            EspoFieldSchema(name="cProjectInterest", type="varchar"),
            EspoFieldSchema(name="cBudget", type="currency"),
        ],
    )

    recommendation = recommend_mapping(schema)
    by_purpose = {item.purpose: item for item in recommendation.mappings}

    assert by_purpose["email"].matched_field == "emailAddress"
    assert by_purpose["project_interest"].matched_field == "cProjectInterest"
    assert by_purpose["budget"].matched_field == "cBudget"
    assert by_purpose["intent"].matched_field is None
    assert recommendation.matched >= 8
    assert recommendation.missing >= 1


def test_mapping_is_case_insensitive_without_guessing_unknown_fields():
    schema = EspoEntitySchema(
        entity_type="Lead",
        field_count=2,
        fields=[
            EspoFieldSchema(name="CINTENT", type="varchar"),
            EspoFieldSchema(name="unrelatedCustomField", type="varchar"),
        ],
    )

    recommendation = recommend_mapping(schema)
    by_purpose = {item.purpose: item for item in recommendation.mappings}

    assert by_purpose["intent"].matched_field == "CINTENT"
    assert by_purpose["intent"].confidence == "case_insensitive"
    assert all(item.matched_field != "unrelatedCustomField" for item in recommendation.mappings)
