from dataclasses import dataclass, field, asdict

SOURCE_NAMES = {"yad2": "יד2", "homeless": "הומלס", "komo": "קומו"}


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str | None = None
    neighborhood: str | None = None   # normalized, see normalize.norm_neighborhood
    street: str | None = None
    house_number: str | None = None
    rooms: float | None = None
    floor: int | None = None
    sqm: float | None = None
    price: int | None = None
    has_mamad: bool | None = None     # None = the ad doesn't say
    has_balcony: bool | None = None
    has_parking: bool | None = None
    has_elevator: bool | None = None
    is_broker: bool | None = None
    phone: str | None = None
    description: str | None = None
    images: list[str] = field(default_factory=list)
    entry_date: str | None = None
    # filled in after insert
    id: int | None = None
    group_id: int | None = None

    def to_row(self) -> dict:
        row = asdict(self)
        row.pop("id")
        row.pop("group_id")
        return row

    @classmethod
    def from_row(cls, row: dict) -> "Listing":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in row.items() if k in names})

    def text(self) -> str:
        return " ".join(filter(None, [self.title, self.street, self.description]))
