"""
Seed test data for development and testing.
"""

from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import hash_password


TEST_ACCOUNTS = [
    {
        "email": "student@test.shikshasathi.io",
        "password": "TestPass123!",
        "name": "Test Student",
        "role": "student",
    },
    {
        "email": "teacher@test.shikshasathi.io",
        "password": "SecurePass456!",
        "name": "Test Teacher",
        "role": "teacher",
    },
    {
        "email": "admin@test.shikshasathi.io",
        "password": "AdminPass789!",
        "name": "Admin User",
        "role": "admin",
    },
]


def seed_test_data(db: Session) -> None:
    """Populate test accounts if they don't exist."""
    for account in TEST_ACCOUNTS:
        existing = db.query(User).filter(User.email == account["email"]).first()
        if not existing:
            user = User(
                email=account["email"],
                hashed_password=hash_password(account["password"]),
                name=account["name"],
                role=account["role"],
                is_active=True,
            )
            db.add(user)
    db.commit()
