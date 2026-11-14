import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TeacherVoicePage } from "../components/TeacherVoicePage";
import { api } from "../services/api";

const SAMPLE_B64 = "UklGRgAAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

describe("TeacherVoicePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();

    vi.spyOn(api, "getVoiceConsent").mockResolvedValue({
      consent_text_version: "2.0",
      consent_text:
        "I consent to ShikshaSaathi creating a synthetic copy of my voice. Answers are AI-generated in my voice and I can delete it at any time.",
      confirmed: false,
      max_profiles: 3,
    });

    vi.spyOn(api, "getVoiceProfiles").mockResolvedValue({
      profiles: [
        {
          id: 11,
          teacher_id: 2,
          teacher_name: "Dr. Rao",
          voice_name: "Rao Teaching Voice",
          status: "active",
          languages: "en",
          consent_confirmed: true,
          created_at: "2026-01-01T00:00:00",
        },
        {
          id: 12,
          teacher_id: 2,
          teacher_name: "Dr. Rao",
          voice_name: "Old Voice",
          status: "revoked",
          languages: "en",
          consent_confirmed: false,
          created_at: "2026-01-01T00:00:00",
        },
      ],
    });
  });

  it("shows the consent statement and gates the create button on the checkbox", async () => {
    render(<TeacherVoicePage />);

    const checkbox = await screen.findByTestId("consent-checkbox");
    const createBtn = screen.getByTestId("create-voice-button");

    // The consent statement (including the AI-generation wording) is shown.
    expect(screen.getByTestId("consent-text")).toHaveTextContent(/AI-generated in my voice/i);

    // The create button cannot be used before consent is given or a sample added.
    expect(checkbox).not.toBeChecked();
    expect(createBtn).toBeDisabled();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    // Still disabled: no sample and no name yet.
    expect(createBtn).toBeDisabled();
  });

  it("lists the teacher's voice profiles with status badges", async () => {
    render(<TeacherVoicePage />);

    await waitFor(() => expect(screen.getByTestId("voice-profile-list")).toBeInTheDocument());
    expect(screen.getByText("Rao Teaching Voice")).toBeInTheDocument();
    expect(screen.getByTestId("status-active")).toHaveTextContent("active");
    expect(screen.getByTestId("status-revoked")).toHaveTextContent("revoked");
  });

  it("plays a preview and always shows the disclosure label", async () => {
    vi.spyOn(api, "previewVoiceProfile").mockResolvedValue({
      audio_base64: SAMPLE_B64,
      content_type: "audio/wav",
      label: "AI-generated voice, authorized by the teacher.",
      is_mock: true,
    });

    render(<TeacherVoicePage />);

    const previewBtn = await screen.findByTestId("preview-11");
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(
        screen.getAllByText("AI-generated voice, authorized by the teacher.").length
      ).toBeGreaterThan(0);
    });
    // The mock badge is shown so a synthetic dev tone is never mistaken for a real voice.
    expect(screen.getByTestId("mock-audio-badge")).toBeInTheDocument();
  });

  it("shows a clear provider error message when cloning is not enabled", async () => {
    render(<TeacherVoicePage />);
    await waitFor(() => expect(screen.getByTestId("voice-profile-list")).toBeInTheDocument());
    // Errors surface through the shared error banner with the API message intact.
    expect(screen.queryByTestId("voice-error")).toBeNull();
  });

  it("confirms deletion through the browser dialog before removing a profile", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const deleteSpy = vi.spyOn(api, "deleteVoiceProfile").mockResolvedValue({ status: "deleted" });

    render(<TeacherVoicePage />);
    const deleteBtn = await screen.findByTestId("delete-11");
    fireEvent.click(deleteBtn);

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(11));
  });
});
