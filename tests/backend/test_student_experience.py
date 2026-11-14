"""
Tests for Student Experience additions:
- Document streaming security (ready check, teacher isolation, 401 unauthenticated)
- Student preferences (get/set, validation of active voice profiles)
- Voice profile listing (only active with confirmed consent)
- TTS synthesis (default voice, cloned voice with authorized label, graceful fallback)
- Student chapter listing (all chapters, with ready-document flags; ready_only still filters)
"""

import io
import os
import pytest
from unittest.mock import MagicMock, patch

from app.models.chapter import Chapter
from app.models.document import Document
from app.models.subject import Subject
from app.models.user_preference import UserPreference
from app.models.voice_profile import VoiceProfile


def register_and_login(client, email, name, role):
    client.post("/auth/register", json={
        "email": email,
        "name": name,
        "password": "password123",
        "role": role
    })
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def test_unauthenticated_file_stream_401(client):
    response = client.get("/documents/1/file")
    assert response.status_code == 401


def test_document_file_access_controls(client, db_session, tmp_path):
    teacher1_token = register_and_login(client, "t1_file@example.com", "Teacher One", "teacher")
    teacher2_token = register_and_login(client, "t2_file@example.com", "Teacher Two", "teacher")
    student_token = register_and_login(client, "s_file@example.com", "Student File", "student")

    # Teacher 1 creates subject and chapter
    subj1 = Subject(name="Physics", teacher_id=1)
    db_session.add(subj1)
    db_session.commit()

    chap1 = Chapter(subject_id=subj1.id, title="Optics", order=1)
    db_session.add(chap1)
    db_session.commit()

    # Create dummy files on disk
    file1_path = str(tmp_path / "optics_ready.pdf")
    with open(file1_path, "wb") as f:
        f.write(b"%PDF-1.4 dummy pdf content for testing")

    file2_path = str(tmp_path / "optics_pending.pdf")
    with open(file2_path, "wb") as f:
        f.write(b"%PDF-1.4 pending pdf content")

    doc_ready = Document(
        filename="optics_ready.pdf",
        file_path=file1_path,
        status="ready",
        chapter_id=chap1.id,
    )
    doc_pending = Document(
        filename="optics_pending.pdf",
        file_path=file2_path,
        status="pending",
        chapter_id=chap1.id,
    )
    db_session.add_all([doc_ready, doc_pending])
    db_session.commit()

    # 1. Student CAN stream ready document
    res_student_ready = client.get(
        f"/documents/{doc_ready.id}/file",
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_student_ready.status_code == 200
    assert res_student_ready.headers["content-type"] == "application/pdf"
    assert b"%PDF-1.4 dummy pdf" in res_student_ready.content

    # 2. Student CANNOT stream pending/non-ready document (403)
    res_student_pending = client.get(
        f"/documents/{doc_pending.id}/file",
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_student_pending.status_code == 403
    assert "not ready" in res_student_pending.json()["detail"]

    # 3. Teacher 1 CAN stream their own documents (both ready and pending)
    res_t1_ready = client.get(
        f"/documents/{doc_ready.id}/file",
        headers={"Authorization": f"Bearer {teacher1_token}"}
    )
    assert res_t1_ready.status_code == 200

    res_t1_pending = client.get(
        f"/documents/{doc_pending.id}/file",
        headers={"Authorization": f"Bearer {teacher1_token}"}
    )
    assert res_t1_pending.status_code == 200

    # 4. Teacher 2 CANNOT read Teacher 1's files (403)
    res_t2 = client.get(
        f"/documents/{doc_ready.id}/file",
        headers={"Authorization": f"Bearer {teacher2_token}"}
    )
    assert res_t2.status_code == 403
    assert "does not own" in res_t2.json()["detail"]


def test_student_preferences_flow(client, db_session):
    student_token = register_and_login(client, "student_pref@example.com", "Student Pref", "student")
    teacher_token = register_and_login(client, "teacher_vp@example.com", "Teacher VP", "teacher")

    # 1. Get default preferences
    get_res = client.get("/me/preferences", headers={"Authorization": f"Bearer {student_token}"})
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["voice_profile_id"] is None
    assert data["question_language"] == "indic-auto"
    assert data["answer_language"] == "en"

    # Create active voice profile with confirmed consent
    vp_active = VoiceProfile(
        teacher_id=2,
        voice_name="Prof Verma Voice",
        status="active",
        consent_confirmed=True,
        consent_text="I confirm consent.",
    )
    # Create inactive voice profile without consent
    vp_inactive = VoiceProfile(
        teacher_id=2,
        voice_name="Draft Voice",
        status="pending",
        consent_confirmed=False,
    )
    db_session.add_all([vp_active, vp_inactive])
    db_session.commit()

    # 2. Saving inactive voice profile -> 400 Bad Request
    bad_put = client.put(
        "/me/preferences",
        json={"voice_profile_id": vp_inactive.id, "question_language": "hi-IN", "answer_language": "hi"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert bad_put.status_code == 400
    assert "not active or lacks confirmed" in bad_put.json()["detail"]

    # 3. Saving active voice profile -> 200 OK
    good_put = client.put(
        "/me/preferences",
        json={"voice_profile_id": vp_active.id, "question_language": "kn-IN", "answer_language": "kn"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert good_put.status_code == 200
    saved = good_put.json()
    assert saved["voice_profile_id"] == vp_active.id
    assert saved["question_language"] == "kn-IN"
    assert saved["answer_language"] == "kn"

    # 4. Verify GET returns updated values
    check_get = client.get("/me/preferences", headers={"Authorization": f"Bearer {student_token}"})
    assert check_get.status_code == 200
    assert check_get.json()["voice_profile_id"] == vp_active.id


def test_voices_listing_filters_unconfirmed(client, db_session):
    student_token = register_and_login(client, "student_vlist@example.com", "Student VList", "student")

    vp1 = VoiceProfile(
        teacher_id=1,
        voice_name="Confirmed Teacher Voice",
        status="active",
        consent_confirmed=True,
    )
    vp2 = VoiceProfile(
        teacher_id=1,
        voice_name="Unconfirmed Teacher Voice",
        status="active",
        consent_confirmed=False,
    )
    vp3 = VoiceProfile(
        teacher_id=1,
        voice_name="Disabled Teacher Voice",
        status="disabled",
        consent_confirmed=True,
    )
    db_session.add_all([vp1, vp2, vp3])
    db_session.commit()

    res = client.get("/voices", headers={"Authorization": f"Bearer {student_token}"})
    assert res.status_code == 200
    voices = res.json()
    names = [v["voice_name"] for v in voices]
    assert "Confirmed Teacher Voice" in names
    assert "Unconfirmed Teacher Voice" not in names
    assert "Disabled Teacher Voice" not in names


def test_tts_speak_default_voice(client):
    student_token = register_and_login(client, "student_tts1@example.com", "Student TTS 1", "student")

    res = client.post(
        "/tts/speak",
        json={"text": "Photosynthesis is the process by which green plants make food.", "voice_profile_id": None},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["voice_used"] == "default"
    assert data["is_cloned"] is False
    assert data["fallback"] is False
    assert data["label"] is None
    assert len(data["audio_base64"]) > 50


def test_tts_speak_cloned_voice_authorized(client, db_session):
    student_token = register_and_login(client, "student_tts2@example.com", "Student TTS 2", "student")

    vp = VoiceProfile(
        teacher_id=1,
        voice_name="Dr. Raman Voice",
        status="active",
        consent_confirmed=True,
        gnani_voice_id="dr_raman_cloned",
    )
    db_session.add(vp)
    db_session.commit()

    res = client.post(
        "/tts/speak",
        json={"text": "Light travels in straight lines.", "voice_profile_id": vp.id},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["voice_used"] == "cloned"
    assert data["is_cloned"] is True
    assert data["fallback"] is False
    assert data["label"] == "AI-generated voice, authorized by the teacher."
    assert len(data["audio_base64"]) > 50


def test_tts_speak_fallback_when_voice_fails(client, db_session):
    student_token = register_and_login(client, "student_tts3@example.com", "Student TTS 3", "student")

    vp = VoiceProfile(
        teacher_id=1,
        voice_name="Failing Teacher Voice",
        status="active",
        consent_confirmed=True,
        gnani_voice_id="fail_voice",
    )
    db_session.add(vp)
    db_session.commit()

    # Simulate cloned voice synthesis failure
    with patch("app.api.tts.get_tts_service") as mock_get_tts:
        mock_service = MagicMock()

        def side_effect(text, voice_id=None, language="en", is_cloned=False):
            if is_cloned:
                raise RuntimeError("Voice cloning backend unavailable")
            return b"RIFF....WAVEfmt ....data...."

        mock_service.synthesize_speech.side_effect = side_effect
        mock_get_tts.return_value = mock_service

        res = client.post(
            "/tts/speak",
            json={"text": "Testing fallback mechanism.", "voice_profile_id": vp.id},
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["voice_used"] == "default"
        assert data["is_cloned"] is False
        assert data["fallback"] is True
        assert "Teacher voice unavailable" in data["notice"]


def test_student_sees_all_chapters_with_ready_flags(client, db_session):
    teacher_token = register_and_login(client, "teacher_chaps@example.com", "Teacher Chaps", "teacher")
    student_token = register_and_login(client, "student_chaps@example.com", "Student Chaps", "student")

    subj = Subject(name="Geology", teacher_id=1)
    db_session.add(subj)
    db_session.commit()

    chap_with_ready = Chapter(subject_id=subj.id, title="Plate Tectonics", order=1)
    chap_without_ready = Chapter(subject_id=subj.id, title="Mineralogy (Empty)", order=2)
    db_session.add_all([chap_with_ready, chap_without_ready])
    db_session.commit()

    doc_ready = Document(
        filename="tectonics.pdf",
        file_path="/tmp/tectonics.pdf",
        status="ready",
        chapter_id=chap_with_ready.id,
    )
    doc_pending = Document(
        filename="minerals_pending.pdf",
        file_path="/tmp/minerals.pdf",
        status="pending",
        chapter_id=chap_without_ready.id,
    )
    db_session.add_all([doc_ready, doc_pending])
    db_session.commit()

    # Student listing chapters -> sees BOTH chapters, with readiness flags
    student_res = client.get(
        f"/subjects/{subj.id}/chapters",
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert student_res.status_code == 200
    by_title = {chap["title"]: chap for chap in student_res.json()}
    assert set(by_title) == {"Plate Tectonics", "Mineralogy (Empty)"}
    assert by_title["Plate Tectonics"]["has_ready_documents"] is True
    assert by_title["Plate Tectonics"]["ready_document_count"] == 1
    assert by_title["Mineralogy (Empty)"]["has_ready_documents"] is False
    assert by_title["Mineralogy (Empty)"]["ready_document_count"] == 0

    # ready_only=true still filters down to chapters that have ready documents
    filtered_res = client.get(
        f"/subjects/{subj.id}/chapters?ready_only=true",
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert filtered_res.status_code == 200
    assert [chap["title"] for chap in filtered_res.json()] == ["Plate Tectonics"]

    # Teacher behavior unchanged: still sees both chapters, same flags
    teacher_res = client.get(
        f"/subjects/{subj.id}/chapters",
        headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert teacher_res.status_code == 200
    assert len(teacher_res.json()) == 2
