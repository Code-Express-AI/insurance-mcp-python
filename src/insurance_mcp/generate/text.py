"""Accident descriptions and adjuster notes, built from the text library in text/.

The library is a few hundred short pieces of text with gaps such as {store} and
{vehicle}. The gaps are filled from the claim's own data, so a theft claim never
gets a windshield note, and the store named is one you'd find in that city.

A note is an opening, three middle sentences and a closing, each picked
separately. That gives millions of different notes from a small library.
"""

import datetime
import json
import random
from pathlib import Path

from insurance_mcp.generate import reference
from insurance_mcp.generate.config import AS_OF_DATE
from insurance_mcp.generate.records import Claim, ClaimNote

TEXT_DIR = Path(__file__).parent / "text"
DESCRIPTIONS = json.loads((TEXT_DIR / "descriptions.json").read_text(encoding="utf-8"))
NOTES = json.loads((TEXT_DIR / "notes.json").read_text(encoding="utf-8"))


def gap_values(rng: random.Random, claim: Claim) -> dict[str, str]:
    """What goes in each gap, taken from the claim where possible."""
    customer = claim.policy.customer
    vehicle = claim.policy.vehicle
    city = reference.CITIES_BY_NAME[customer.city]
    return {
        "customer": f"{customer.first_name} {customer.last_name}",
        "customer_last_name": customer.last_name,
        "driver": f"{claim.driver.first_name} {claim.driver.last_name}",
        "street_address": customer.street_address,
        "phone": customer.phone,
        "city": customer.city,
        "vehicle": f"{vehicle.model_year} {vehicle.make} {vehicle.model}",
        "make": vehicle.make,
        "shop": claim.repair_shop.name if claim.repair_shop else "the shop",
        "reserve": f"${claim.reserve:,.2f}",
        "loss_date": f"{claim.date_of_loss:%B} {claim.date_of_loss.day}",
        "road": rng.choice(city.roads),
        "street": rng.choice(reference.STREETS),
        "store": rng.choice(reference.STORES),
        "other_vehicle": rng.choice(reference.OTHER_VEHICLES),
    }


def description_kind(claim: Claim) -> str:
    """Collisions are told differently depending on whose fault they were."""
    if claim.claim_type == "collision":
        return f"collision_{claim.fault}"
    return claim.claim_type


def fill(template: str, values: dict[str, str]) -> str:
    """Fill the gaps, then start with a capital: '{other_vehicle} ran' -> 'A pickup ran'."""
    filled = template.format_map(values)
    return filled[0].upper() + filled[1:]


def make_description(rng: random.Random, claim: Claim) -> str:
    template = rng.choice(DESCRIPTIONS[description_kind(claim)])
    return fill(template, gap_values(rng, claim))


def note_stages(rng: random.Random, claim: Claim) -> list[str]:
    """The stages a claim's notes go through, in order.

    Big claims (an injury or over $15,000) get more investigation notes. Open
    claims stop where they've got to.
    """
    big = claim.injury_cost > 0 or claim.reserve > 15_000
    investigations = rng.randint(3, 6) if big else rng.randint(1, 3)
    stages = ["first_report"] + ["investigation"] * investigations
    stages.append("total_loss" if claim.total_loss else "estimate")
    closing = {"settled": "settlement", "denied": "denial", "withdrawn": "withdrawal"}

    if claim.status == "open":
        # How far an open claim has got depends on how long it's been open.
        days_open = (AS_OF_DATE - claim.date_reported).days
        return stages[: 1 + min(len(stages) - 1, days_open // 7)]
    return [*stages, closing[claim.status]]


def make_note(rng: random.Random, stage: str, claim: Claim) -> str:
    """An opening, three different middle sentences and a closing. The middles
    include ones written for this claim type, and ones about injuries if someone was hurt."""
    pieces = NOTES[stage]
    middles = pieces["middle"] + pieces.get("middle_by_type", {}).get(claim.claim_type, [])
    if claim.injury_cost > 0:
        middles += pieces.get("middle_injury", [])
    sentences = [
        rng.choice(pieces["opening"]),
        *rng.sample(middles, 3),
        rng.choice(pieces["closing"]),
    ]
    return fill(" ".join(sentences), gap_values(rng, claim))


def make_notes(rng: random.Random, claim: Claim) -> list[ClaimNote]:
    """About five notes per claim, dated in order between reporting and closing."""
    texts = [make_note(rng, stage, claim) for stage in note_stages(rng, claim)]
    # Planted notes (planted.py) go in after the first report.
    texts[1:1] = claim.planted_notes

    last_day = claim.date_closed or AS_OF_DATE
    days = sorted(
        claim.date_reported
        + datetime.timedelta(days=rng.randint(0, (last_day - claim.date_reported).days))
        for _ in texts
    )
    # The first note is written the day the claim is reported, the closing one the day it closes.
    days[0] = claim.date_reported
    if claim.date_closed:
        days[-1] = claim.date_closed

    notes = []
    for day, note in zip(days, texts, strict=True):
        # Stored in UTC. 14:00 to 23:00 UTC is office hours in the Central and Mountain time zones.
        created_at = datetime.datetime(
            day.year,
            day.month,
            day.day,
            rng.randint(14, 22),
            rng.randint(0, 59),
            tzinfo=datetime.UTC,
        )
        notes.append(ClaimNote(claim.adjuster, created_at, note))
    return notes
