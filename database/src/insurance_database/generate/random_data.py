"""The random part of the data: customers, policies, claims and their payments.

Every function takes the one random.Random object, so the same seed always
gives the same data. Never use the module-level random functions here.
"""

import datetime
import random
from decimal import Decimal

from insurance_database.generate import reference, text
from insurance_database.generate.config import AS_OF_DATE, START_DATE, years_before
from insurance_database.generate.records import (
    Adjuster,
    Claim,
    ClaimPayment,
    Customer,
    Dataset,
    Driver,
    Policy,
    RepairShop,
    Vehicle,
)

# The claim types each coverage level pays for (see the coverage levels in spec.md).
# Liability only pays for damage you cause to others, so its claims are collisions.
COVERED_CLAIM_TYPES = {
    "liability": ("collision",),
    "liability_collision": ("collision",),
    "full": ("collision", "glass", "weather", "vandalism", "theft", "fire"),
}
CLAIM_TYPE_WEIGHTS = {
    "collision": 55,
    "glass": 15,
    "weather": 13,
    "vandalism": 8,
    "theft": 6,
    "fire": 3,
}

# Days from reporting a claim to closing it, by claim type.
DAYS_TO_CLOSE = {
    "glass": (2, 14),
    "vandalism": (10, 40),
    "weather": (10, 45),
    "collision": (14, 60),
    "theft": (20, 75),
    "fire": (20, 60),
}

# Claims older than this are always closed. Only the planted claims stay open
# longer (planted.py), so "open claims more than 90 days old" is a short list.
MAX_DAYS_OPEN = 90

DEDUCTIBLES = (250, 500, 1000, 1500, 2000)
DEDUCTIBLE_WEIGHTS = (10, 45, 30, 10, 5)


# Small helpers ---------------------------------------------------------------------


def money(amount: float) -> Decimal:
    """Dollars and cents, as the database stores them."""
    return Decimal(f"{amount:.2f}")


def random_date(rng: random.Random, start: datetime.date, end: datetime.date) -> datetime.date:
    return start + datetime.timedelta(days=rng.randint(0, (end - start).days))


def age_on(date_of_birth: datetime.date, day: datetime.date) -> int:
    had_birthday = (day.month, day.day) >= (date_of_birth.month, date_of_birth.day)
    return day.year - date_of_birth.year - (0 if had_birthday else 1)


def birth_date(rng: random.Random, age: int) -> datetime.date:
    """A date of birth that makes someone `age` on the as-of date."""
    latest = years_before(AS_OF_DATE, age)
    return latest - datetime.timedelta(days=rng.randint(0, 364))


def pick_name(rng: random.Random, last_name: str | None = None) -> tuple[str, str]:
    """A random first and last name. Never Maria Garcia: the demos need exactly one."""
    while True:
        first = rng.choice(reference.FIRST_NAMES)
        last = last_name or rng.choice(reference.LAST_NAMES)
        if (first, last) != ("Maria", "Garcia"):
            return first, last


# Reference data --------------------------------------------------------------------


def make_repair_shops(rng: random.Random, count: int) -> list[RepairShop]:
    """At least one shop in every city, the rest spread by city size."""
    cities = list(reference.CITIES)
    weights = [city.weight for city in cities]
    cities += rng.choices(cities, weights=weights, k=count - len(cities))
    names = rng.sample(
        [
            f"{start} {end}"
            for start in reference.SHOP_NAME_STARTS
            for end in reference.SHOP_NAME_ENDS
        ],
        count,
    )
    return [
        RepairShop(name, city.name, city.state, price_factor=rng.uniform(0.9, 1.15))
        for name, city in zip(names, cities, strict=True)
    ]


def make_adjusters(rng: random.Random, count: int) -> list[Adjuster]:
    adjusters, seen = [], set()
    while len(adjusters) < count:
        name = pick_name(rng)
        if name not in seen:
            seen.add(name)
            adjusters.append(Adjuster(*name))
    return adjusters


# Customers and policies ------------------------------------------------------------


def make_customer(rng: random.Random, licenses: set[str]) -> Customer:
    first, last = pick_name(rng)
    date_of_birth = birth_date(rng, round(rng.triangular(18, 85, 42)))
    city = rng.choices(reference.CITIES, weights=[c.weight for c in reference.CITIES])[0]
    return Customer(
        first_name=first,
        last_name=last,
        date_of_birth=date_of_birth,
        street_address=f"{rng.randint(10, 9899)} {rng.choice(reference.STREETS)}",
        city=city.name,
        state=city.state,
        zip_code=rng.choice(city.zip_codes),
        email=make_email(rng, first, last, date_of_birth),
        phone=make_phone(rng, city.area_code),
        drivers_license_number=make_license_number(rng, licenses),
    )


def make_email(rng: random.Random, first: str, last: str, date_of_birth: datetime.date) -> str:
    """Always @example.com, but the part before the @ varies, as real addresses do.

    If every email were first.last, the masked m***@example.com next to the name
    Maria Garcia would give the whole address away.
    """
    first, last = first.lower(), last.lower()
    local = rng.choice(
        (
            f"{first}.{last}",
            f"{first[0]}{last}{date_of_birth.year % 100:02d}",
            f"{first}.{last[0]}",
            f"{last}.family",
            f"{first[0]}{last[0]}{date_of_birth.year}",
            f"{first}{rng.randint(1, 99)}",
            f"{last}{first[0]}",
        )
    )
    return f"{local}@example.com"


def make_phone(rng: random.Random, area_code: str) -> str:
    """The city's real area code, with a 555-01xx number, which is reserved for fiction."""
    return f"({area_code}) 555-01{rng.randint(0, 99):02d}"


def make_license_number(rng: random.Random, licenses: set[str]) -> str:
    """A made-up shape, like K47-2083-9152, so it can't be mistaken for a real one."""
    while True:
        letter = chr(ord("A") + rng.randint(0, 25))
        digits = f"{rng.randint(0, 9_999_999_999):010d}"
        number = f"{letter}{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        if number not in licenses:
            licenses.add(number)
            return number


def make_license_plate(rng: random.Random) -> str:
    letters = "".join(chr(ord("A") + rng.randint(0, 25)) for _ in range(3))
    return f"{letters}-{rng.randint(1000, 9999)}"


def make_vehicle(rng: random.Random) -> Vehicle:
    model = rng.choices(
        reference.VEHICLE_MODELS, weights=[m.weight for m in reference.VEHICLE_MODELS]
    )[0]
    model_year = rng.randint(AS_OF_DATE.year - 16, AS_OF_DATE.year)
    # Cars lose about 15% of their value a year.
    value = max(2_000, model.new_value * 0.85 ** (AS_OF_DATE.year - model_year))
    return Vehicle(
        license_plate=make_license_plate(rng),
        make=model.make,
        model=model.model,
        model_year=model_year,
        value=money(round(value, -2)),
    )


def make_household(rng: random.Random, customer: Customer) -> list[Driver]:
    """The policyholder, sometimes a spouse, and sometimes a teenage or young adult child."""
    drivers = [
        Driver(customer.first_name, customer.last_name, customer.date_of_birth, "policyholder")
    ]
    age = age_on(customer.date_of_birth, AS_OF_DATE)
    if age >= 22 and rng.random() < 0.25:
        drivers.append(
            make_family_member(rng, customer, drivers, max(18, age + rng.randint(-5, 5)), "spouse")
        )
    if age >= 38 and rng.random() < 0.13:
        drivers.append(make_family_member(rng, customer, drivers, rng.randint(17, 22), "child"))
    return drivers


def make_family_member(
    rng: random.Random, customer: Customer, drivers: list[Driver], age: int, relationship: str
) -> Driver:
    """Usually shares the customer's last name. Never shares a first name with another driver."""
    last_name = customer.last_name if rng.random() < 0.85 else None
    while True:
        first, last = pick_name(rng, last_name)
        if all(first != driver.first_name for driver in drivers):
            return Driver(first, last, birth_date(rng, age), relationship)


def make_policy(rng: random.Random, customer: Customer, drivers: list[Driver]) -> Policy:
    vehicle = make_vehicle(rng)
    # Older cars are more often insured for liability only.
    if vehicle.model_year < AS_OF_DATE.year - 11:
        level_weights = (50, 25, 25)
    else:
        level_weights = (15, 25, 60)
    coverage_level = rng.choices(
        ("liability", "liability_collision", "full"), weights=level_weights
    )[0]

    # Liability only covers other people's cars, so there's no deductible to pay.
    deductible = 0
    if coverage_level != "liability":
        deductible = rng.choices(DEDUCTIBLES, weights=DEDUCTIBLE_WEIGHTS)[0]

    base_premium = {"liability": 850, "liability_collision": 1400, "full": 1900}[coverage_level]
    young_driver = any(age_on(d.date_of_birth, AS_OF_DATE) < 25 for d in drivers)
    premium = base_premium * rng.uniform(0.8, 1.25) * (1.45 if young_driver else 1.0)
    premium -= deductible * 0.15  # a higher deductible means a lower premium

    start_date = random_date(
        rng,
        AS_OF_DATE - datetime.timedelta(days=13 * 365),
        AS_OF_DATE - datetime.timedelta(days=31),
    )
    end_date, status = None, "active"
    earliest_end = max(start_date + datetime.timedelta(days=60), START_DATE)
    if rng.random() < 0.10 and earliest_end < AS_OF_DATE:
        end_date, status = (
            random_date(rng, earliest_end, AS_OF_DATE - datetime.timedelta(days=1)),
            "canceled",
        )

    return Policy(
        customer=customer,
        coverage_level=coverage_level,
        premium=money(round(premium)),
        deductible=money(deductible),
        start_date=start_date,
        end_date=end_date,
        status=status,
        vehicle=vehicle,
        # Each policy gets its own driver records (see the simplifications in spec.md).
        drivers=[
            Driver(d.first_name, d.last_name, d.date_of_birth, d.relationship) for d in drivers
        ],
    )


def add_customers_and_policies(rng: random.Random, data: Dataset, customer_count: int) -> None:
    licenses = {customer.drivers_license_number for customer in data.customers}
    for _ in range(customer_count):
        customer = make_customer(rng, licenses)
        household = make_household(rng, customer)
        data.customers.append(customer)
        # About a quarter of customers insure a second car.
        for _ in range(2 if rng.random() < 0.25 else 1):
            data.policies.append(make_policy(rng, customer, household))


# Claims ----------------------------------------------------------------------------


def random_active_policy(
    rng: random.Random,
    data: Dataset,
    day: datetime.date,
    claim_type: str,
    coverage_levels: tuple[str, ...] = ("liability", "liability_collision", "full"),
    state: str | None = None,
) -> Policy:
    """A random policy that was active on `day` and pays for this type of claim."""
    while True:
        policy = rng.choice(data.policies)
        if (
            policy.is_active_on(day)
            and claim_type in COVERED_CLAIM_TYPES[policy.coverage_level]
            and policy.coverage_level in coverage_levels
            and (state is None or policy.customer.state == state)
        ):
            return policy


def make_claim(
    rng: random.Random,
    data: Dataset,
    policy: Policy,
    date_of_loss: datetime.date,
    claim_type: str,
    date_reported: datetime.date | None = None,
) -> Claim:
    """One claim, with its status, dates, cost and description worked out to fit together."""
    # Who was driving. Only a collision has someone at the wheel, so the other
    # claim types record the policyholder. Nobody drives before they're 16.
    driver = policy.drivers[0]
    if claim_type == "collision":
        old_enough = [d for d in policy.drivers if age_on(d.date_of_birth, date_of_loss) >= 16]
        driver = rng.choice(old_enough)

    fault = "not_at_fault"
    if claim_type == "collision":
        if policy.coverage_level == "liability":
            # Liability pays when you damage someone else's car.
            fault = rng.choices(("at_fault", "shared"), weights=(75, 25))[0]
        elif age_on(driver.date_of_birth, date_of_loss) < 20:
            fault = rng.choices(("at_fault", "not_at_fault", "shared"), weights=(65, 20, 15))[0]
        else:
            fault = rng.choices(("at_fault", "not_at_fault", "shared"), weights=(45, 40, 15))[0]

    # What it will cost, and whether a repair shop is needed.
    injury, total_loss = False, False
    vehicle_value = float(policy.vehicle.value)
    match claim_type:
        case "glass":
            cost = rng.uniform(250, 1400)
        case "collision":
            cost = min(rng.lognormvariate(8.4, 0.6), 20_000)  # about $4,500 on average
            injury = rng.random() < 0.08
        case "weather":
            cost = rng.uniform(1500, 9000)
        case "vandalism":
            cost = rng.uniform(300, 4000)
        case "theft":
            # Most stolen cars are never found. A found one usually needs repairs.
            cost = rng.uniform(800, 6000) if rng.random() < 0.4 else vehicle_value
        case "fire":
            cost = vehicle_value if rng.random() < 0.7 else rng.uniform(2000, 12000)
    if cost >= 0.75 * vehicle_value:
        cost, total_loss = vehicle_value, True

    repair_shop = None
    if not total_loss:
        repair_shop = nearby_repair_shop(rng, data, policy.customer)
        cost *= repair_shop.price_factor
    injury_cost = rng.uniform(10_000, 45_000) if injury else 0
    cost += injury_cost

    # When it was reported, and whether it's closed yet.
    if date_reported is None:
        delay = rng.choices((0, 1, 2, 3, 5, 7, 14), weights=(30, 25, 15, 10, 10, 6, 4))[0]
        date_reported = min(date_of_loss + datetime.timedelta(days=delay), AS_OF_DATE)
    days_since_reported = (AS_OF_DATE - date_reported).days
    status, date_closed = "open", None
    if days_since_reported > MAX_DAYS_OPEN or rng.random() < days_since_reported / 100:
        low, high = DAYS_TO_CLOSE[claim_type]
        days_to_close = rng.randint(low, high) + (rng.randint(30, 150) if injury else 0)
        date_closed = date_reported + datetime.timedelta(
            days=min(days_to_close, days_since_reported)
        )
        status = rng.choices(("settled", "denied", "withdrawn"), weights=(83, 7, 10))[0]

    claim = Claim(
        policy=policy,
        driver=driver,
        adjuster=rng.choice(data.adjusters),
        repair_shop=repair_shop,
        claim_type=claim_type,
        fault=fault,
        status=status,
        date_of_loss=date_of_loss,
        date_reported=date_reported,
        date_closed=date_closed,
        reserve=money(round(cost)),
        description="",
        injury_cost=money(injury_cost),
        total_loss=total_loss,
    )
    claim.description = text.make_description(rng, claim)
    return claim


def nearby_repair_shop(rng: random.Random, data: Dataset, customer: Customer) -> RepairShop:
    """A shop in the customer's city if there is one, otherwise in their state."""
    in_city = [s for s in data.repair_shops if s.city == customer.city]
    in_state = [s for s in data.repair_shops if s.state == customer.state]
    return rng.choice(in_city or in_state)


def add_claims(rng: random.Random, data: Dataset, claim_count: int) -> None:
    """Claims spread evenly over the three years, each on a policy active that day."""
    types = list(CLAIM_TYPE_WEIGHTS)
    weights = list(CLAIM_TYPE_WEIGHTS.values())
    for _ in range(claim_count):
        date_of_loss = random_date(rng, START_DATE, AS_OF_DATE)
        claim_type = rng.choices(types, weights=weights)[0]
        policy = random_active_policy(rng, data, date_of_loss, claim_type)
        data.claims.append(make_claim(rng, data, policy, date_of_loss, claim_type))


# Numbers, payments and notes, once every record exists ----------------------------


def give_out_numbers(rng: random.Random, data: Dataset) -> None:
    """Random policy and claim numbers for the records that don't have one yet.

    Planted numbers start with 1 (AUT-104233, CLM-1024817) and random ones never
    do, so the two can't clash.
    """
    policies = [p for p in data.policies if not p.policy_number]
    for policy, number in zip(
        policies, rng.sample(range(200_000, 1_000_000), len(policies)), strict=True
    ):
        policy.policy_number = f"AUT-{number}"

    claims = [c for c in data.claims if not c.claim_number]
    for claim, number in zip(
        claims, rng.sample(range(2_000_000, 10_000_000), len(claims)), strict=True
    ):
        claim.claim_number = f"CLM-{number}"


def add_payments(rng: random.Random, claim: Claim) -> None:
    """Settled claims get one to three payments. Other claims get none.

    A claim that costs less than the deductible pays nothing, so it's withdrawn.
    """
    if claim.status != "settled":
        return

    vehicle_cost = float(claim.reserve - claim.injury_cost)
    payable = vehicle_cost * rng.uniform(0.85, 1.05) - float(claim.policy.deductible)
    if payable < 50 and not claim.injury_cost:
        claim.status = "withdrawn"
        return

    if claim.injury_cost:
        injury = float(claim.injury_cost) * rng.uniform(0.8, 1.0)
        claim.payments.append(ClaimPayment("injury", money(injury), claim.date_closed))
    if claim.claim_type in ("collision", "theft", "weather") and rng.random() < 0.55:
        rental = rng.uniform(200, 1200)
        payment_date = random_date(rng, claim.date_reported, claim.date_closed)
        claim.payments.append(ClaimPayment("rental_car", money(rental), payment_date))
    if payable < 50:
        return

    if claim.total_loss:
        claim.payments.append(ClaimPayment("total_loss", money(payable), claim.date_closed))
        return
    # A repair is sometimes paid in two parts: the estimate, then a supplement
    # for damage found once the shop took the car apart.
    if len(claim.payments) < 2 and rng.random() < 0.35:
        first = payable * rng.uniform(0.6, 0.85)
        payment_date = random_date(rng, claim.date_reported, claim.date_closed)
        claim.payments.append(ClaimPayment("repair", money(first), payment_date))
        payable -= first
    claim.payments.append(ClaimPayment("repair", money(payable), claim.date_closed))


def add_payments_and_notes(rng: random.Random, data: Dataset) -> None:
    for claim in data.claims:
        add_payments(rng, claim)
        claim.notes = text.make_notes(rng, claim)
