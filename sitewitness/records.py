"""Records: the sample files, and which roles may open them.

All files, people and buildings here are made up (sample data).
The helper can only ever open a file listed here; it never opens a path it is sent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT / "samples" / "records"


@dataclass(frozen=True)
class Record:
    id: str
    title: str
    filename: str
    words: tuple[str, ...]   # phrases a person might use for this file (English and Arabic)
    roles: tuple[str, ...]   # roles allowed to open or send it

    @property
    def path(self) -> Path:
        return FILES_DIR / self.filename


RECORDS: tuple[Record, ...] = (
    Record("alnoor-slides", "Al Noor Residence · Law 3 slides", "al-noor-law3-slides.pdf",
           ("al noor", "alnoor", "slides", "slide", "deck", "presentation", "النور", "عرض", "العرض", "الشرائح"),
           ("owner", "broker", "engineer")),
    Record("alnoor-report", "Al Noor Residence · signed Law 3 report", "al-noor-signed-report.pdf",
           ("al noor", "alnoor", "report", "signed report", "safety report", "النور", "التقرير", "تقرير"),
           ("owner", "engineer")),
    Record("marina-quote", "Marina Court · inspection quote", "marina-court-quote.pdf",
           ("marina", "marina court", "quote", "price", "مارينا", "عرض السعر"),
           ("owner", "broker")),
    Record("clinic-dha", "Sample Family Clinic · DHA self-inspection report", "sample-clinic-dha-report.pdf",
           ("clinic", "dha", "checklist", "report", "inspection", "العيادة"),
           ("owner",)),
)
BY_ID = {r.id: r for r in RECORDS}

from .people import PEOPLE  # noqa: E402  (the real people: run/people.json, set up on the Mac)

# made-up people for tests only; a normal run never uses them
SAMPLE_PEOPLE = {
    "layla": {"name": "Layla Mansour", "role": "owner", "email": "layla@example.com"},
    "omar": {"name": "Omar Khan", "role": "broker", "email": "omar@example.com"},
    "visitor": {"name": "Visitor", "role": "visitor", "email": ""},
}


def allowed(person_id: str, record: Record) -> bool:
    person = PEOPLE.get(person_id)
    return bool(person) and person["role"] in record.roles
