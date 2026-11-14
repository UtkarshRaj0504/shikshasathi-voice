import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AudioPlayer } from "../components/AudioPlayer";
import { StudentDashboard } from "../components/StudentDashboard";
import { api } from "../services/api";

describe("AudioPlayer Component", () => {
  it("renders loading state correctly", () => {
    render(<AudioPlayer loading={true} />);
    expect(screen.getByText(/Synthesizing voice response/i)).toBeInTheDocument();
  });

  it("renders error state correctly", () => {
    const handleRetry = vi.fn();
    render(<AudioPlayer error="Network error" onRetry={handleRetry} />);
    expect(screen.getByText(/Network error/i)).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: /Retry Audio/i });
    fireEvent.click(retryBtn);
    expect(handleRetry).toHaveBeenCalled();
  });

  it("renders cloned voice with mandatory transparency label", () => {
    // 1-byte base64 valid string
    const sampleB64 = "UklGRgAAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
    render(
      <AudioPlayer
        audioBase64={sampleB64}
        isCloned={true}
        label="AI-generated voice, authorized by the teacher."
      />
    );

    expect(
      screen.getByText("AI-generated voice, authorized by the teacher.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /▶ Play|⏸ Pause/i })).toBeInTheDocument();
  });

  it("renders fallback notice when voice clone fails or falls back", () => {
    const sampleB64 = "UklGRgAAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
    render(
      <AudioPlayer
        audioBase64={sampleB64}
        isCloned={false}
        fallback={true}
        notice="Teacher voice unavailable; used default voice."
      />
    );

    expect(
      screen.getByText(/Teacher voice unavailable; used default voice./i)
    ).toBeInTheDocument();
  });
});

describe("StudentDashboard Flow", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getMe").mockResolvedValue({
      id: 1,
      name: "Rahul",
      email: "student@example.com",
      role: "student",
    });

    vi.spyOn(api, "getSubjects").mockResolvedValue([
      { id: 10, name: "Science", description: "Physics & Chemistry" },
    ]);

    vi.spyOn(api, "getChapters").mockResolvedValue([
      { id: 101, title: "Light - Reflection & Refraction", order: 1, subject_id: 10 },
    ]);

    vi.spyOn(api, "getVoices").mockResolvedValue([
      {
        id: 201,
        teacher_id: 2,
        teacher_name: "Dr. Sharma",
        voice_name: "Dr. Sharma's Voice",
        status: "active",
        consent_confirmed: true,
        is_cloned: true,
      },
    ]);

    vi.spyOn(api, "getPreferences").mockResolvedValue({
      voice_profile_id: null,
      question_language: "indic-auto",
      answer_language: "en",
    });
  });

  it("navigates through Subject, Chapter, and Choose Teacher Voice step", async () => {
    const handleLogout = vi.fn();
    render(<StudentDashboard onLogout={handleLogout} />);

    // Step 1: Wait for subjects to load
    await waitFor(() => {
      expect(screen.getByText(/Science/i)).toBeInTheDocument();
    });

    // Select subject
    const subjectSelect = screen.getByRole("combobox");
    fireEvent.change(subjectSelect, { target: { value: "10" } });

    // Wait for chapters
    await waitFor(() => {
      expect(screen.getByText(/Light - Reflection & Refraction/i)).toBeInTheDocument();
    });

    // Select chapter
    fireEvent.click(screen.getByText(/Light - Reflection & Refraction/i));

    // Click proceed to choose teacher voice
    const continueBtn = screen.getByRole("button", { name: /Continue to Choose Teacher Voice/i });
    expect(continueBtn).not.toBeDisabled();
    fireEvent.click(continueBtn);

    // Step 2: Choose teacher voice
    await waitFor(() => {
      expect(screen.getByText(/Choose How Your AI Tutor Speaks/i)).toBeInTheDocument();
      expect(screen.getByText(/Default AI Voice \(Standard\)/i)).toBeInTheDocument();
      expect(screen.getAllByText(/Dr. Sharma's Voice/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Authorized Cloned Voice/i).length).toBeGreaterThan(0);
    });
  });
});
