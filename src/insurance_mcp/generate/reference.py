"""Small hand-written lists the random data is picked from.

The places are real: real cities, a few of each city's real ZIP codes, its real
area code and real highways. US readers would spot a made-up city or a ZIP code
from the wrong place. Everything else here is made up.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    state: str
    area_code: str
    zip_codes: tuple[str, ...]
    roads: tuple[str, ...]
    # Roughly the population in thousands, so big cities get more customers.
    weight: int


# A regional insurer in five southwestern states.
# One row per city reads better than the formatter's layout, so it's left alone.
# fmt: off
CITIES = (
    City("Austin", "TX", "512", ("78701", "78704", "78745", "78753"), ("I-35", "MoPac", "US-183"), 970),
    City("Dallas", "TX", "214", ("75201", "75204", "75214", "75230"), ("I-35E", "I-635", "US-75"), 1300),
    City("Houston", "TX", "713", ("77002", "77006", "77019", "77057"), ("I-45", "I-610", "I-10"), 2300),
    City("San Antonio", "TX", "210", ("78205", "78209", "78216", "78230"), ("I-10", "I-410", "US-281"), 1450),
    City("Fort Worth", "TX", "817", ("76102", "76107", "76116", "76132"), ("I-30", "I-35W", "I-820"), 950),
    City("El Paso", "TX", "915", ("79901", "79912", "79925"), ("I-10", "Loop 375"), 680),
    City("Plano", "TX", "972", ("75023", "75024", "75093"), ("US-75", "the Dallas North Tollway"), 290),
    City("Oklahoma City", "OK", "405", ("73102", "73112", "73120", "73132"), ("I-40", "I-35", "I-44"), 690),
    City("Tulsa", "OK", "918", ("74103", "74105", "74133", "74136"), ("I-44", "US-169", "US-75"), 410),
    City("Norman", "OK", "405", ("73069", "73071", "73072"), ("I-35", "Main Street"), 130),
    City("Denver", "CO", "303", ("80202", "80205", "80210", "80220"), ("I-25", "I-70", "Colfax Avenue"), 715),
    City("Colorado Springs", "CO", "719", ("80903", "80907", "80918", "80920"), ("I-25", "Powers Boulevard"), 480),
    City("Aurora", "CO", "303", ("80010", "80012", "80015"), ("I-225", "E-470"), 390),
    City("Fort Collins", "CO", "970", ("80521", "80524", "80525", "80526"), ("I-25", "College Avenue"), 170),
    City("Albuquerque", "NM", "505", ("87102", "87108", "87110", "87120"), ("I-25", "I-40", "Central Avenue"), 560),
    City("Santa Fe", "NM", "505", ("87501", "87505", "87507"), ("I-25", "Cerrillos Road"), 90),
    City("Las Cruces", "NM", "575", ("88001", "88005", "88011"), ("I-10", "I-25"), 110),
    City("Phoenix", "AZ", "602", ("85003", "85008", "85016", "85032"), ("I-10", "I-17", "Loop 101"), 1650),
    City("Tucson", "AZ", "520", ("85701", "85711", "85716", "85745"), ("I-10", "Speedway Boulevard"), 545),
    City("Mesa", "AZ", "480", ("85201", "85203", "85210"), ("US-60", "Loop 202"), 505),
    City("Scottsdale", "AZ", "480", ("85251", "85254", "85260"), ("Loop 101", "Scottsdale Road"), 240),
)
# fmt: on

CITIES_BY_NAME = {city.name: city for city in CITIES}


@dataclass(frozen=True)
class VehicleModel:
    make: str
    model: str
    new_value: int  # roughly what it costs new, in dollars
    weight: int  # how common it is


VEHICLE_MODELS = (
    VehicleModel("Ford", "F-150", 52_000, 12),
    VehicleModel("Chevrolet", "Silverado 1500", 50_000, 9),
    VehicleModel("Ram", "1500", 50_000, 7),
    VehicleModel("Toyota", "Camry", 30_000, 8),
    VehicleModel("Toyota", "RAV4", 33_000, 8),
    VehicleModel("Toyota", "Corolla", 24_000, 6),
    VehicleModel("Toyota", "Tacoma", 38_000, 5),
    VehicleModel("Honda", "Civic", 27_000, 6),
    VehicleModel("Honda", "CR-V", 33_000, 7),
    VehicleModel("Nissan", "Altima", 28_000, 5),
    VehicleModel("Jeep", "Grand Cherokee", 45_000, 4),
    VehicleModel("Ford", "Explorer", 42_000, 4),
    VehicleModel("Chevrolet", "Equinox", 30_000, 5),
    VehicleModel("Subaru", "Outback", 34_000, 4),
    VehicleModel("Hyundai", "Elantra", 23_000, 4),
    VehicleModel("Tesla", "Model 3", 42_000, 3),
)

# fmt: off
FIRST_NAMES = (
    "James", "Mary", "Michael", "Jennifer", "David", "Linda", "Robert", "Patricia",
    "John", "Elizabeth", "William", "Susan", "Richard", "Jessica", "Joseph", "Sarah",
    "Thomas", "Karen", "Christopher", "Emily", "Daniel", "Ashley", "Matthew", "Amanda",
    "Anthony", "Melissa", "Mark", "Stephanie", "Steven", "Nicole", "Andrew", "Rebecca",
    "Joshua", "Laura", "Kevin", "Megan", "Brian", "Rachel", "Tyler", "Hannah",
    "Brandon", "Olivia", "Ethan", "Madison", "Noah", "Emma", "Logan", "Chloe",
    "Jose", "Maria", "Luis", "Ana", "Carlos", "Sofia", "Juan", "Gabriela",
    "Miguel", "Isabel", "Alejandro", "Lucia", "Diego", "Carmen", "Javier", "Elena",
    "Raj", "Priya", "Arjun", "Ananya", "Vikram", "Divya", "Rohan", "Neha",
    "Sanjay", "Kavya", "Wei", "Mei", "Minh", "Linh", "Jin", "Grace",
)

# Rutherford isn't here: the demos need exactly one, so it's planted (planted.py).
LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson",
    "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Thompson", "White",
    "Harris", "Clark", "Lewis", "Walker", "Hall", "Allen", "Young", "King",
    "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Hill", "Campbell",
    "Mitchell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Parker", "Collins",
    "Edwards", "Stewart", "Morris", "Murphy", "Cook", "Rogers", "Morgan", "Cooper",
    "Peterson", "Reed", "Bailey", "Bell", "Kelly", "Howard", "Ward", "Brooks",
    "Bennett", "Gray", "Hughes", "Price", "Sanders", "Foster", "Ross", "Long",
    "Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Perez", "Sanchez",
    "Ramirez", "Torres", "Flores", "Rivera", "Gomez", "Diaz", "Reyes", "Cruz",
    "Morales", "Ortiz", "Gutierrez", "Chavez", "Patel", "Shah", "Sharma", "Singh",
    "Kumar", "Gupta", "Reddy", "Rao", "Nguyen", "Tran", "Kim", "Lee", "Chen", "Wang",
)

STREETS = (
    "Elm Street", "Oak Avenue", "Maple Drive", "Cedar Lane", "Pine Street", "Willow Way",
    "Main Street", "Park Avenue", "Lakeview Drive", "Hillcrest Road", "Ridge Road",
    "Meadow Lane", "Spring Street", "Highland Avenue", "Cherry Lane", "Washington Street",
    "Lincoln Avenue", "Jefferson Street", "Mesa Drive", "Canyon Road", "Mesquite Lane",
    "Juniper Drive", "Aspen Court", "Cottonwood Drive", "Pecan Street", "Magnolia Avenue",
    "Sage Court", "Prairie View Road", "Sunrise Drive", "Quail Run",
)
# fmt: on

# Stores and places for the accident stories.
# fmt: off
STORES = (
    "Walmart", "Target", "Costco", "7-Eleven", "Home Depot", "Walgreens", "CVS",
    "Kroger", "Safeway", "Starbucks", "McDonald's", "Lowe's",
)

OTHER_VEHICLES = (
    "a pickup truck", "a white SUV", "a delivery van", "a silver sedan", "a semi truck",
    "a minivan", "a black pickup", "a landscaping truck", "a red hatchback", "a motorcycle",
)

# Made-up repair shop names: one word from each list. Nothing here matches the
# planted shop's name (planted.py).
SHOP_NAME_STARTS = (
    "Precision", "Summit", "Canyon", "Desert Sun", "Red Rock", "Frontier", "Prairie",
    "Mesa", "Lone Star", "Mile High", "Sooner", "Pinnacle", "Pioneer", "Sundance",
    "Bluebonnet", "Roadrunner", "Trailhead", "Cornerstone", "Sierra", "Arroyo",
)
SHOP_NAME_ENDS = (
    "Collision Center", "Auto Body", "Body & Paint", "Collision Repair", "Auto Works",
)
# fmt: on
