"""The records the generator makes: one class per table, plus the whole dataset.

Records point at each other (a policy has its customer), not at ids. The
database creates the ids when the rows are loaded (see database.py).

eq=False on every class: two customers with the same details are still two
customers.
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(eq=False)
class Customer:
    first_name: str
    last_name: str
    date_of_birth: datetime.date
    street_address: str
    city: str
    state: str
    zip_code: str
    email: str
    phone: str
    drivers_license_number: str  # unique, so the loader can find the row again


@dataclass(eq=False)
class Vehicle:
    license_plate: str
    make: str
    model: str
    model_year: int
    value: Decimal


@dataclass(eq=False)
class Driver:
    first_name: str  # unique within a policy, so the loader can find the row again
    last_name: str
    date_of_birth: datetime.date
    relationship: str


@dataclass(eq=False)
class Policy:
    customer: Customer
    coverage_level: str
    premium: Decimal
    deductible: Decimal
    start_date: datetime.date
    end_date: datetime.date | None
    status: str
    vehicle: Vehicle
    drivers: list[Driver]
    policy_number: str = ""  # given out once every policy exists

    def is_active_on(self, day: datetime.date) -> bool:
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)


@dataclass(eq=False)
class RepairShop:
    name: str
    city: str
    state: str
    # Not a column. How this shop's prices compare with the average (1.0).
    price_factor: float = 1.0


@dataclass(eq=False)
class Adjuster:
    first_name: str
    last_name: str


@dataclass(eq=False)
class ClaimPayment:
    payment_type: str
    amount: Decimal
    payment_date: datetime.date


@dataclass(eq=False)
class ClaimNote:
    adjuster: Adjuster
    created_at: datetime.datetime
    note: str


@dataclass(eq=False)
class Claim:
    policy: Policy
    driver: Driver
    adjuster: Adjuster
    repair_shop: RepairShop | None
    claim_type: str
    fault: str
    status: str
    date_of_loss: datetime.date
    date_reported: datetime.date
    date_closed: datetime.date | None
    reserve: Decimal
    description: str
    claim_number: str = ""  # given out once every claim exists
    # Not columns. They decide which payments and notes the claim gets.
    injury_cost: Decimal = Decimal(0)  # the part of the reserve that is for injuries
    total_loss: bool = False
    planted_notes: list[str] = field(default_factory=list)
    payments: list[ClaimPayment] = field(default_factory=list)
    notes: list[ClaimNote] = field(default_factory=list)


@dataclass
class Dataset:
    customers: list[Customer] = field(default_factory=list)
    policies: list[Policy] = field(default_factory=list)
    repair_shops: list[RepairShop] = field(default_factory=list)
    adjusters: list[Adjuster] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
