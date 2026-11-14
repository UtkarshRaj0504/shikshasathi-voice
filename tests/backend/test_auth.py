"""
Tests for authentication and user management endpoints.
"""

def test_register_teacher(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "teacher@example.com",
            "name": "Dr. Sharma",
            "password": "securepassword123",
            "role": "teacher"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "teacher@example.com"
    assert data["name"] == "Dr. Sharma"
    assert data["role"] == "teacher"
    assert "id" in data


def test_register_student(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "student@example.com",
            "name": "Rahul",
            "password": "securepassword123",
            "role": "student"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "student"


def test_register_duplicate_email(client):
    payload = {
        "email": "duplicate@example.com",
        "name": "User One",
        "password": "password123",
        "role": "student"
    }
    res1 = client.post("/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_login_success(client):
    client.post(
        "/auth/register",
        json={
            "email": "login@example.com",
            "name": "Login User",
            "password": "mypassword123",
            "role": "student"
        }
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "login@example.com",
            "password": "mypassword123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={
            "email": "login2@example.com",
            "name": "Login User 2",
            "password": "mypassword123",
            "role": "student"
        }
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "login2@example.com",
            "password": "wrongpassword"
        }
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_get_me(client):
    client.post(
        "/auth/register",
        json={
            "email": "me@example.com",
            "name": "Me User",
            "password": "password123",
            "role": "teacher"
        }
    )
    login_res = client.post(
        "/auth/login",
        json={"email": "me@example.com", "password": "password123"}
    )
    token = login_res.json()["access_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@example.com"
    assert data["name"] == "Me User"


def test_role_protections(client):
    # Register a teacher and a student
    client.post("/auth/register", json={"email": "t@ex.com", "name": "T", "password": "password123", "role": "teacher"})
    client.post("/auth/register", json={"email": "s@ex.com", "name": "S", "password": "password123", "role": "student"})

    t_token = client.post("/auth/login", json={"email": "t@ex.com", "password": "password123"}).json()["access_token"]
    s_token = client.post("/auth/login", json={"email": "s@ex.com", "password": "password123"}).json()["access_token"]

    # Teacher accessing teacher-only -> OK
    assert client.get("/auth/teacher-only", headers={"Authorization": f"Bearer {t_token}"}).status_code == 200
    # Student accessing teacher-only -> 403 Forbidden
    assert client.get("/auth/teacher-only", headers={"Authorization": f"Bearer {s_token}"}).status_code == 403

    # Student accessing student-only -> OK
    assert client.get("/auth/student-only", headers={"Authorization": f"Bearer {s_token}"}).status_code == 200
    # Teacher accessing student-only -> 403 Forbidden
    assert client.get("/auth/student-only", headers={"Authorization": f"Bearer {t_token}"}).status_code == 403
