"""Shared pieces of OCDS release packages used by the UK and AusTender sources."""

from __future__ import annotations

import re

from src.normalize import clean_text, coerce_number, first_text

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _add_classification(parts: list[str], classification) -> None:
    if not isinstance(classification, dict):
        return
    bit = " ".join(
        str(part)
        for part in (
            classification.get("scheme"),
            classification.get("id"),
            classification.get("description"),
        )
        if part
    )
    if bit and bit not in parts:
        parts.append(bit)


def category_from_tender(tender: dict | None) -> str | None:
    tender = tender or {}
    parts: list[str] = []
    _add_classification(parts, tender.get("classification"))
    for extra in tender.get("additionalClassifications") or []:
        _add_classification(parts, extra)
    for item in tender.get("items") or []:
        if not isinstance(item, dict):
            continue
        _add_classification(parts, item.get("classification"))
        for extra in item.get("additionalClassifications") or []:
            _add_classification(parts, extra)
    return "; ".join(parts) or None


def buyer_name(release: dict) -> str | None:
    buyer = release.get("buyer")
    if isinstance(buyer, dict) and buyer.get("name"):
        return clean_text(str(buyer["name"]))
    for party in release.get("parties") or []:
        if not isinstance(party, dict):
            continue
        roles = {str(role).lower() for role in (party.get("roles") or [])}
        if roles & {"buyer", "procuringentity"} and party.get("name"):
            return clean_text(str(party["name"]))
    return None


def tender_value(tender: dict | None):
    tender = tender or {}
    value = tender.get("value") if isinstance(tender.get("value"), dict) else {}
    amount = coerce_number(value.get("amount")) if value else None
    currency = clean_text(value.get("currency")) if value else None
    return amount, currency


def find_tender_url(release: dict) -> str | None:
    release_id = str(release.get("id") or "")
    if release_id:
        return f"https://www.find-tender.service.gov.uk/Notice/{release_id}"
    return None


def contracts_finder_url(release: dict) -> str | None:
    match = _UUID.search(str(release.get("id") or ""))
    if match:
        return f"https://www.contractsfinder.service.gov.uk/Notice/{match.group(0)}"
    ocid = release.get("ocid")
    if ocid:
        return f"https://www.contractsfinder.service.gov.uk/Notice/{ocid}"
    return None


def release_notice_id(release: dict) -> str | None:
    ocid = clean_text(str(release.get("ocid"))) if release.get("ocid") else None
    release_id = clean_text(str(release.get("id"))) if release.get("id") else None
    if ocid and release_id:
        return f"{ocid}/{release_id}"
    return release_id or ocid


def ocds_tender_partial(release: dict, *, source: str, country: str, url: str | None) -> dict:
    tender = release.get("tender") if isinstance(release.get("tender"), dict) else {}
    amount, currency = tender_value(tender)
    period = tender.get("tenderPeriod") if isinstance(tender.get("tenderPeriod"), dict) else {}
    description = tender.get("description")
    return {
        "title": first_text(tender.get("title")),
        "buyer": buyer_name(release),
        "country": country,
        "category": category_from_tender(tender),
        "value": amount,
        "currency": currency,
        "publishedDate": release.get("date") or tender.get("datePublished"),
        "deadline": period.get("endDate") if period else None,
        "url": url,
        "noticeId": release_notice_id(release),
        "source": source,
        "description": description if isinstance(description, str) else first_text(description),
    }


def austender_contract_partial(release: dict) -> dict | None:
    """Best-effort row for an awarded contract notice. Not an open tender."""
    contracts = [item for item in (release.get("contracts") or []) if isinstance(item, dict)]
    contract = contracts[0] if contracts else {}
    title = first_text(contract.get("title")) or first_text((release.get("tender") or {}).get("title"))
    if not title:
        return None
    value = contract.get("value") if isinstance(contract.get("value"), dict) else {}
    items = contract.get("items") if isinstance(contract.get("items"), list) else []
    category = category_from_tender({"items": items})
    contract_id = clean_text(str(contract.get("id"))) if contract.get("id") else None
    url = None
    if contract_id and contract_id.upper().startswith("CN"):
        url = f"https://www.tenders.gov.au/Cn/Show/{contract_id}"
    return {
        "title": title,
        "buyer": buyer_name(release),
        "country": "AUS",
        "category": category,
        "value": coerce_number(value.get("amount")) if value else None,
        "currency": value.get("currency") if value else None,
        "publishedDate": release.get("date"),
        "deadline": None,
        "url": url,
        "noticeId": release_notice_id(release),
        "source": "austender",
        "description": contract.get("description") if isinstance(contract.get("description"), str) else None,
    }
