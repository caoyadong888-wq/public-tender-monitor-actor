"""Dataset schema accepts the nulls that normalize.finalize emits."""

import json
from pathlib import Path

import pytest

from src.normalize import finalize
from src.ocds import ocds_tender_partial
from src.sources import canadabuys, sam_gov, ted
from tests.test_offline import FETCHED, make_ctx

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def test_normalized_items_match_dataset_schema():
    document = json.loads((ROOT / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
    fields = document["fields"]
    validator = jsonschema.Draft7Validator(fields)

    ted_notice = json.loads((FIXTURES / "ted_notice.json").read_text(encoding="utf-8"))
    ocds_release = json.loads((FIXTURES / "ocds_release.json").read_text(encoding="utf-8"))
    sam_opportunity = json.loads((FIXTURES / "sam_opportunity.json").read_text(encoding="utf-8"))
    canada_csv = (FIXTURES / "canada_sample.csv").read_text(encoding="utf-8")

    items = [
        finalize(ted.parse_ted_notice(ted_notice), FETCHED),
        finalize(
            ocds_tender_partial(ocds_release, source="uk_fts", country="GBR", url=None),
            FETCHED,
        ),
        *canadabuys.items_from_csv(canada_csv, make_ctx()),
        finalize(sam_gov.parse_opportunity(sam_opportunity), FETCHED),
        finalize({"title": "x"}, FETCHED),
    ]
    assert items
    for item in items:
        assert item is not None
        errors = list(validator.iter_errors(item))
        assert not errors, errors
        assert set(fields["properties"]) == set(item)
