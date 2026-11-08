"""Deterministic starter library records stored as simulated files."""

from __future__ import annotations

import json

from kernel.filesystem import FileSystem


BOOKS = (
    ("The Left Hand of Darkness", "Ursula K. Le Guin", "Science Fiction"),
    ("Pride and Prejudice", "Jane Austen", "Classic"),
    ("The Hobbit", "J. R. R. Tolkien", "Fantasy"),
    ("Kindred", "Octavia E. Butler", "Science Fiction"),
    ("The Dispossessed", "Ursula K. Le Guin", "Science Fiction"),
    ("Beloved", "Toni Morrison", "Literary Fiction"),
    ("Frankenstein", "Mary Shelley", "Classic"),
    ("The Martian", "Andy Weir", "Science Fiction"),
    ("A Wizard of Earthsea", "Ursula K. Le Guin", "Fantasy"),
    ("The Name of the Rose", "Umberto Eco", "Mystery"),
    ("Invisible Cities", "Italo Calvino", "Literary Fiction"),
    ("Things Fall Apart", "Chinua Achebe", "Classic"),
    ("The Color Purple", "Alice Walker", "Literary Fiction"),
    ("Dune", "Frank Herbert", "Science Fiction"),
    ("The Fifth Season", "N. K. Jemisin", "Fantasy"),
    ("Rebecca", "Daphne du Maurier", "Mystery"),
    ("The Odyssey", "Homer", "Classic"),
    ("The Book Thief", "Markus Zusak", "Historical Fiction"),
    ("The Three-Body Problem", "Liu Cixin", "Science Fiction"),
    ("Jane Eyre", "Charlotte Brontë", "Classic"),
)

MEMBERS = (
    ("Aarav Shah", "student"), ("Aditi Rao", "student"), ("Amara Okafor", "faculty"),
    ("Arjun Mehta", "student"), ("Chen Wei", "student"), ("Daniel Kim", "faculty"),
    ("Diya Patel", "student"), ("Elena García", "student"), ("Fatima Hassan", "faculty"),
    ("Grace Chen", "student"), ("Hana Suzuki", "student"), ("Ibrahim Ali", "student"),
    ("Isabella Rossi", "faculty"), ("Kabir Nair", "student"), ("Leila Mansour", "student"),
    ("Liam O'Connor", "student"), ("Maya Johnson", "faculty"), ("Noah Williams", "student"),
    ("Olivia Martin", "student"), ("Priya Kapoor", "student"), ("Ravi Iyer", "faculty"),
    ("Sofia Petrov", "student"), ("Theo Brown", "student"), ("Yuki Tanaka", "student"),
    ("Zara Khan", "student"),
)


def seed_filesystem(filesystem: FileSystem) -> None:
    """Populate books, members, issue history, and fines in virtual directories."""
    for index in range(60):
        title, author, category = BOOKS[index % len(BOOKS)]
        book_id = f"B{index + 1:03}"
        record = {
            "id": book_id,
            "isbn": f"978-1-{index + 100:03}-{index * 37 % 10000:04}-{index % 10}",
            "title": title if index < len(BOOKS) else f"{title}: Volume {index // len(BOOKS) + 1}",
            "author": author,
            "publisher": ("Northstar Press", "Cedar House", "Open Shelf Publishing")[index % 3],
            "category": category,
            "year": 1970 + (index * 7) % 55,
            "shelf_location": f"{chr(65 + index % 20)}-{index // 20 + 1:02}",
            "total_copies": 1 + index % 5,
            "available_copies": 1 + index % 5,
            "price": round(9.99 + (index * 1.73) % 40, 2),
        }
        _write_json(filesystem, f"/books/{book_id}.json", record)

    for index, (name, role) in enumerate(MEMBERS, start=1):
        member_id = f"M{index:03}"
        record = {
            "id": member_id,
            "name": name,
            "role": role,
            "email": f"{name.split()[0].lower()}.{index:02}@libraos.example",
            "phone": f"+1-555-{1000 + index:04}",
            "join_date": f"2025-{index % 12 + 1:02}-01",
            "max_books_allowed": 5 if role == "faculty" else 3,
            "fines_due": 0.0,
            "status": "active",
        }
        _write_json(filesystem, f"/members/{member_id}.json", record)

    for index in range(20):
        issue_id = f"I{index + 1:03}"
        issued_day = 1 + index % 12
        issue_date = f"2026-09-{issued_day:02}"
        due_date = f"2026-09-{issued_day + 14:02}"
        is_overdue = index < 8
        record = {
            "id": issue_id,
            "book_id": f"B{index + 1:03}",
            "member_id": f"M{index + 1:03}",
            "issue_date": issue_date,
            "due_date": due_date,
            "return_date": None if index < 12 else f"2026-09-{issued_day + 10:02}",
            "fine": round((30 - issued_day) * 0.5, 2) if is_overdue else 0.0,
            "status": "overdue" if is_overdue else ("issued" if index < 12 else "returned"),
        }
        _write_json(filesystem, f"/issued/{issue_id}.json", record)
        if is_overdue:
            fine = {
                "id": f"F{index + 1:03}",
                "issue_id": issue_id,
                "member_id": record["member_id"],
                "amount": record["fine"],
                "status": "unpaid",
            }
            _write_json(filesystem, f"/fines/F{index + 1:03}.json", fine)

    _write_json(
        filesystem,
        "/etc/libraos.json",
        {"name": "LibraOS", "stage": 2, "default_user": "guest", "seed": 20261030},
    )
    filesystem.create_file("/logs/audit.log", "LibraOS Stage 2 disk initialized\n", owner="root")


def _write_json(filesystem: FileSystem, path: str, record: dict[str, object]) -> None:
    filesystem.create_file(
        path,
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        owner="librarian",
    )
