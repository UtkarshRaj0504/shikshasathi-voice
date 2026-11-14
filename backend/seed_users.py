from app.core.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password

db = SessionLocal()
try:
    # Check if teacher exists
    teacher = db.query(User).filter(User.email == "teacher@example.com").first()
    if not teacher:
        t = User(
            email="teacher@example.com",
            name="Dr. Sharma",
            hashed_password=hash_password("password123"),
            role="teacher"
        )
        db.add(t)
        print("Created teacher@example.com")

    # Check if student exists
    student = db.query(User).filter(User.email == "student@example.com").first()
    if not student:
        s = User(
            email="student@example.com",
            name="Rahul",
            hashed_password=hash_password("password123"),
            role="student"
        )
        db.add(s)
        print("Created student@example.com")

    db.commit()
    print("Seeding completed successfully!")
finally:
    db.close()
