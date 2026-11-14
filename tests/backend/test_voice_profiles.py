"""
Tests for teacher voice cloning endpoints and VoiceConsent workflow.
Verifies consent requirement, role checks, teacher isolation, and revoke flow.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import status


def _teacher_token(client, email="teacher1@example.com"):
    """Register and login a teacher."""
    client.post(
        "/auth/register",
        json={"email": email, "name": "Dr. Sharma", "password": "password123", "role": "teacher"},
    )
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def _student_token(client):
    """Register and login a student."""
    client.post(
        "/auth/register",
        json={"email": "student1@example.com", "name": "Rahul", "password": "password123", "role": "student"},
    )
    res = client.post("/auth/login", json={"email": "student1@example.com", "password": "password123"})
    return res.json()["access_token"]


def test_voice_profile_endpoints_require_teacher_role(client):
    """Students cannot access voice profile endpoints."""
    token = _student_token(client)

    res = client.get("/voice-profiles/consent", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_get_consent_details_before_confirmation(client):
    """Teacher can view consent text without confirming."""
    token = _teacher_token(client)

    res = client.get("/voice-profiles/consent", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["confirmed"] is False
    assert "consent_text" in data
    assert len(data["consent_text"]) > 100


def test_confirm_consent_creates_record(client):
    """Teacher can confirm consent and a record is created."""
    token = _teacher_token(client)

    res = client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "confirmed"
    assert "confirmed_at" in data

    # Verify it's now confirmed
    res = client.get("/voice-profiles/consent", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["confirmed"] is True


def test_confirm_consent_idempotent(client):
    """Confirming consent twice is safe (idempotent)."""
    token = _teacher_token(client)

    res1 = client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "already_confirmed"


def test_upload_reference_audio_without_consent_fails(client):
    """Cannot upload audio without confirming consent first."""
    token = _teacher_token(client)

    audio_bytes = b"RIFF" + b"\x00" * 1000 + b"WAVEfmt " + b"\x00" * 100

    res = client.post(
        "/voice-profiles/upload-reference-audio",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.wav", audio_bytes, "audio/wav")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "consent" in res.json()["detail"].lower()


def test_upload_reference_audio_with_consent_succeeds(client):
    """After consent, teacher can upload reference audio."""
    token = _teacher_token(client)

    # Confirm consent first
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )

    audio_bytes = b"RIFF" + b"\x00" * 1000 + b"WAVEfmt " + b"\x00" * 100

    res = client.post(
        "/voice-profiles/upload-reference-audio",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.wav", audio_bytes, "audio/wav")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "embedding_id" in data


def test_upload_reference_audio_invalid_format_rejected(client):
    """Invalid audio formats are rejected."""
    token = _teacher_token(client)

    # Confirm consent
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )

    res = client.post(
        "/voice-profiles/upload-reference-audio",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.txt", b"not audio", "text/plain")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST


def test_upload_reference_audio_too_short_rejected(client):
    """Audio shorter than 1000 bytes is rejected."""
    token = _teacher_token(client)

    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )

    res = client.post(
        "/voice-profiles/upload-reference-audio",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.wav", b"short", "audio/wav")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST


def test_create_voice_profile_without_consent_fails(client):
    """Cannot create profile without confirming consent."""
    token = _teacher_token(client)

    res = client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token}"},
        json={"voice_name": "My Voice"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST


def test_create_voice_profile_with_consent_succeeds(client):
    """After consent, teacher can create a voice profile."""
    token = _teacher_token(client)

    # Confirm consent
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )

    res = client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token}"},
        json={"voice_name": "Dr. Sharma's Teaching Voice"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["voice_name"] == "Dr. Sharma's Teaching Voice"
    assert data["status"] == "active"
    assert data["consent_confirmed"] is True


def test_list_teacher_profiles_isolated(client):
    """Teachers only see their own profiles."""
    token1 = _teacher_token(client, "teacher_a@example.com")
    token2 = _teacher_token(client, "teacher_b@example.com")  # Different teacher

    # Teacher 1 creates a profile
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token1}"},
        json={"confirmed": True},
    )
    client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token1}"},
        json={"voice_name": "Teacher 1 Voice"},
    )

    # Teacher 2 creates a profile
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token2}"},
        json={"confirmed": True},
    )
    client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token2}"},
        json={"voice_name": "Teacher 2 Voice"},
    )

    # Teacher 1 lists profiles — should only see their own
    res = client.get("/voice-profiles/list", headers={"Authorization": f"Bearer {token1}"})
    assert res.status_code == 200
    profiles = res.json()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["voice_name"] == "Teacher 1 Voice"


def test_delete_profile_revokes_consent(client):
    """Deleting a profile revokes consent and marks it unavailable."""
    token = _teacher_token(client)

    # Create profile
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )
    res = client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token}"},
        json={"voice_name": "Voice to Delete"},
    )
    profile_id = res.json()["id"]

    # Delete it
    res = client.delete(
        f"/voice-profiles/{profile_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"

    # Verify it's gone
    res = client.get(
        f"/voice-profiles/{profile_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_revoke_consent_deactivates_profile(client):
    """Revoking consent marks profile as inactive but keeps it."""
    token = _teacher_token(client)

    # Create profile
    client.post(
        "/voice-profiles/consent/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed": True},
    )
    res = client.post(
        "/voice-profiles/create",
        headers={"Authorization": f"Bearer {token}"},
        json={"voice_name": "Voice to Revoke"},
    )
    profile_id = res.json()["id"]

    # Revoke consent
    res = client.post(
        f"/voice-profiles/{profile_id}/revoke-consent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200

    # Verify profile is now inactive
    res = client.get(
        f"/voice-profiles/{profile_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "inactive"
    assert data["consent_confirmed"] is False


def test_voices_list_excludes_revoked_profiles(client, db_session):
    """GET /voices only returns active profiles with confirmed consent."""
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    from app.models.voice_profile import VoiceProfile

    # Create teacher with profile
    teacher = User(
        email="teacher_voices@example.com",
        name="Dr. Voices",
        hashed_password=hash_password("pass"),
        role=UserRole.teacher,
    )
    db_session.add(teacher)
    db_session.commit()

    profile_active = VoiceProfile(
        teacher_id=teacher.id,
        voice_name="Active Voice",
        status="active",
        consent_confirmed=True,
    )
    profile_inactive = VoiceProfile(
        teacher_id=teacher.id,
        voice_name="Inactive Voice",
        status="inactive",
        consent_confirmed=False,
    )
    db_session.add(profile_active)
    db_session.add(profile_inactive)
    db_session.commit()

    # List voices (as any authenticated user)
    token = _student_token(client)
    res = client.get("/voices", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    voices = res.json()

    # Only active profile with confirmed consent should appear
    active_voices = [v for v in voices if v["voice_name"] == "Active Voice"]
    inactive_voices = [v for v in voices if v["voice_name"] == "Inactive Voice"]

    assert len(active_voices) == 1
    assert len(inactive_voices) == 0
