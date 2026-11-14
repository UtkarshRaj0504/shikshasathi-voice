import React, { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { AudioPlayer } from "./AudioPlayer";
import { blobToWav } from "../utils/audio";

const READING_SCRIPT =
  "Please read this aloud in a calm, natural voice for about 20 to 30 seconds: " +
  "\u201CToday we are going to learn something new together. Take your time, read " +
  "carefully, and think about each idea step by step. If something is not clear, " +
  "we will go over it again slowly, with a simple example, until it makes sense. " +
  "Learning becomes easy when we practise a little every single day.\u201D";

const MIN_SECONDS = 5;
const MAX_SECONDS = 30;

interface VoiceProfile {
  id: number;
  teacher_id: number;
  teacher_name: string;
  voice_name: string;
  status: string;
  languages?: string | null;
  consent_confirmed: boolean;
  created_at: string;
}

const STATUS_STYLES: Record<string, { bg: string; color: string }> = {
  active: { bg: "#d4edda", color: "#155724" },
  pending: { bg: "#fff3cd", color: "#856404" },
  failed: { bg: "#f8d7da", color: "#721c24" },
  revoked: { bg: "#e2e3e5", color: "#383d41" },
};

export const TeacherVoicePage: React.FC = () => {
  const [consentText, setConsentText] = useState<string>("");
  const [maxProfiles, setMaxProfiles] = useState<number>(3);
  const [consentChecked, setConsentChecked] = useState<boolean>(false);
  const [voiceName, setVoiceName] = useState<string>("");

  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Recording / upload state
  const [mode, setMode] = useState<"record" | "upload">("record");
  const [recording, setRecording] = useState<boolean>(false);
  const [seconds, setSeconds] = useState<number>(0);
  const [level, setLevel] = useState<number>(0);
  const [sampleBlob, setSampleBlob] = useState<Blob | null>(null);
  const [sampleUrl, setSampleUrl] = useState<string | null>(null);
  const [sampleName, setSampleName] = useState<string>("sample.wav");
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Preview state
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [previewAudio, setPreviewAudio] = useState<any>(null);
  const [previewAudioId, setPreviewAudioId] = useState<number | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<any>(null);
  const rafRef = useRef<any>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    loadConsent();
    loadProfiles();
    return () => {
      stopTimers();
      stopStream();
    };
  }, []);

  useEffect(() => {
    return () => {
      if (sampleUrl) URL.revokeObjectURL(sampleUrl);
    };
  }, [sampleUrl]);

  const loadConsent = async () => {
    try {
      const data = await api.getVoiceConsent();
      setConsentText(data.consent_text || "");
      setMaxProfiles(data.max_profiles || 3);
    } catch (err: any) {
      setError(err.message || "Could not load the consent statement.");
    }
  };

  const loadProfiles = async () => {
    setLoading(true);
    try {
      const data = await api.getVoiceProfiles();
      setProfiles(data.profiles || []);
    } catch (err: any) {
      setError(err.message || "Could not load your voice profiles.");
    } finally {
      setLoading(false);
    }
  };

  const stopTimers = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  const stopStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
  };

  const resetSample = () => {
    if (sampleUrl) URL.revokeObjectURL(sampleUrl);
    setSampleBlob(null);
    setSampleUrl(null);
    setSeconds(0);
    setLevel(0);
  };

  const startRecording = async () => {
    setError(null);
    setSuccess(null);
    resetSample();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioContextClass: any = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioContextClass) {
        const ctx = new AudioContextClass();
        audioCtxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteFrequencyData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) sum += data[i];
          setLevel(Math.min(100, Math.round((sum / data.length / 255) * 100)));
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      }

      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        const raw = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const wav = await blobToWav(raw);
        setSampleBlob(wav);
        setSampleName("sample.wav");
        setSampleUrl(URL.createObjectURL(wav));
      };
      mediaRecorderRef.current = recorder;
      recorder.start();

      setRecording(true);
      setSeconds(0);
      timerRef.current = setInterval(() => {
        setSeconds((prev) => {
          const next = prev + 1;
          if (next >= MAX_SECONDS) stopRecording();
          return next;
        });
      }, 1000);
    } catch (err: any) {
      setError("Microphone access was denied or is not supported. Please check permissions or upload a file instead.");
    }
  };

  const stopRecording = () => {
    setRecording(false);
    stopTimers();
    stopStream();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setSuccess(null);
    resetSample();
    setSampleBlob(file);
    setSampleName(file.name || "sample.wav");
    setSampleUrl(URL.createObjectURL(file));
    e.target.value = "";
  };

  const canSubmit =
    consentChecked && !submitting && !!sampleBlob && !!voiceName.trim() && profiles.filter((p) => p.status !== "revoked").length < maxProfiles;

  const handleCreate = async () => {
    if (!canSubmit || !sampleBlob) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const profile = await api.createVoiceProfile(
        sampleBlob,
        voiceName.trim(),
        true,
        undefined,
        sampleName
      );
      setSuccess(`Voice profile "${profile.voice_name}" created and is now active.`);
      setVoiceName("");
      resetSample();
      await loadProfiles();
    } catch (err: any) {
      setError(err.message || "Could not create the voice profile.");
    } finally {
      setSubmitting(false);
    }
  };

  const handlePreview = async (id: number) => {
    setPreviewId(id);
    setPreviewAudio(null);
    setPreviewAudioId(null);
    setError(null);
    try {
      const res = await api.previewVoiceProfile(id);
      setPreviewAudio(res);
      setPreviewAudioId(id);
    } catch (err: any) {
      setError(err.message || "Could not generate the voice preview.");
    } finally {
      setPreviewId(null);
    }
  };

  const handleRevoke = async (profile: VoiceProfile) => {
    if (!confirm(`Revoke "${profile.voice_name}"? Students will immediately stop hearing it.`)) return;
    setError(null);
    try {
      await api.revokeVoiceProfile(profile.id);
      setSuccess(`"${profile.voice_name}" was revoked. Students now use the default voice.`);
      await loadProfiles();
    } catch (err: any) {
      setError(err.message || "Could not revoke the voice profile.");
    }
  };

  const handleDelete = async (profile: VoiceProfile) => {
    if (!confirm(`Delete "${profile.voice_name}" permanently? This also revokes your consent.`)) return;
    setError(null);
    try {
      await api.deleteVoiceProfile(profile.id);
      setSuccess(`"${profile.voice_name}" was deleted.`);
      await loadProfiles();
    } catch (err: any) {
      setError(err.message || "Could not delete the voice profile.");
    }
  };

  const nonRevokedCount = profiles.filter((p) => p.status !== "revoked").length;
  const limitReached = nonRevokedCount >= maxProfiles;

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: "900px" }}>
      <h2 style={{ marginTop: 0 }}>🎙️ My Voice</h2>
      <p style={{ color: "#555", fontSize: "0.95rem" }}>
        Create a safe, authorized copy of your voice so your students can hear study answers
        narrated in your own voice. It is <strong>AI-generated</strong> from a short recording you
        provide, it is clearly labelled to students, and you can revoke or delete it at any time.
      </p>

      {error && (
        <div data-testid="voice-error" style={{ background: "#f8d7da", color: "#842029", padding: "0.75rem 1rem", borderRadius: "6px", marginBottom: "1rem", border: "1px solid #f5c2c7" }}>
          ⚠️ {error}
        </div>
      )}
      {success && (
        <div data-testid="voice-success" style={{ background: "#d1e7dd", color: "#0f5132", padding: "0.75rem 1rem", borderRadius: "6px", marginBottom: "1rem", border: "1px solid #badbcc" }}>
          ✅ {success}
        </div>
      )}

      {/* Consent statement */}
      <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem", marginBottom: "1.5rem" }}>
        <h3 style={{ marginTop: 0 }}>1. Consent</h3>
        <div
          data-testid="consent-text"
          style={{ background: "#f8f9fa", border: "1px solid #e9ecef", borderRadius: "6px", padding: "1rem", maxHeight: "220px", overflowY: "auto", whiteSpace: "pre-wrap", fontSize: "0.9rem", lineHeight: 1.5 }}
        >
          {consentText || "Loading consent statement..."}
        </div>
        <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", marginTop: "1rem", cursor: "pointer", fontWeight: 500 }}>
          <input
            type="checkbox"
            data-testid="consent-checkbox"
            checked={consentChecked}
            onChange={(e) => setConsentChecked(e.target.checked)}
            style={{ marginTop: "0.25rem" }}
          />
          <span>
            I have read the statement above and I consent to ShikshaSaathi creating an
            AI-generated copy of my voice for my students.
          </span>
        </label>
      </div>

      {/* Record / upload */}
      <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem", marginBottom: "1.5rem" }}>
        <h3 style={{ marginTop: 0 }}>2. Record your voice sample</h3>
        <div style={{ background: "#e7f1ff", border: "1px solid #b6d4fe", borderRadius: "6px", padding: "0.75rem 1rem", fontSize: "0.85rem", color: "#084298", marginBottom: "1rem" }}>
          <strong>Tips for a clean recording:</strong> sit in a quiet room, turn off music and fans,
          hold the mic a hand-width away, and speak naturally for {MIN_SECONDS}-{MAX_SECONDS} seconds.
        </div>
        <div style={{ background: "#f8f9fa", border: "1px dashed #ced4da", borderRadius: "6px", padding: "0.75rem 1rem", fontSize: "0.9rem", marginBottom: "1rem" }}>
          <strong>Suggested reading script:</strong>
          <p style={{ margin: "0.4rem 0 0", color: "#495057" }}>{READING_SCRIPT}</p>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <button
            type="button"
            onClick={() => { resetSample(); setMode("record"); }}
            style={{ padding: "0.4rem 0.8rem", borderRadius: "4px", border: "1px solid #ced4da", background: mode === "record" ? "#0d6efd" : "#fff", color: mode === "record" ? "#fff" : "#212529", cursor: "pointer" }}
          >
            🎙️ Record in browser
          </button>
          <button
            type="button"
            onClick={() => { resetSample(); setMode("upload"); }}
            style={{ padding: "0.4rem 0.8rem", borderRadius: "4px", border: "1px solid #ced4da", background: mode === "upload" ? "#0d6efd" : "#fff", color: mode === "upload" ? "#fff" : "#212529", cursor: "pointer" }}
          >
            📁 Upload WAV / MP3
          </button>
        </div>

        {mode === "record" ? (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              {!recording ? (
                <button type="button" data-testid="start-recording" onClick={startRecording} style={{ padding: "0.6rem 1.2rem", background: "#28a745", color: "#fff", border: "none", borderRadius: "20px", fontWeight: "bold", cursor: "pointer" }}>
                  ● Start recording
                </button>
              ) : (
                <button type="button" data-testid="stop-recording" onClick={stopRecording} style={{ padding: "0.6rem 1.2rem", background: "#dc3545", color: "#fff", border: "none", borderRadius: "20px", fontWeight: "bold", cursor: "pointer" }}>
                  ⏹ Stop ({seconds}s)
                </button>
              )}
              {recording && <span style={{ color: "#dc3545", fontWeight: 600 }}>Recording... {seconds}s / {MAX_SECONDS}s</span>}
            </div>
            <div style={{ marginTop: "0.75rem", background: "#e9ecef", borderRadius: "6px", height: "12px", overflow: "hidden", width: "220px" }} title="Input level">
              <div style={{ width: `${level}%`, height: "100%", background: level > 70 ? "#dc3545" : "#28a745", transition: "width 0.1s" }} />
            </div>
          </div>
        ) : (
          <label style={{ display: "block", padding: "1rem", border: "2px dashed #0d6efd", borderRadius: "8px", textAlign: "center", cursor: "pointer", background: "#f0f4f8" }}>
            {sampleBlob && mode === "upload" ? `Selected: ${sampleName}` : "Click to choose a WAV or MP3 file"}
            <input type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" onChange={handleFileUpload} style={{ display: "none" }} />
          </label>
        )}

        {sampleBlob && (
          <div style={{ marginTop: "1rem" }}>
            <div style={{ fontSize: "0.85rem", color: "#495057", marginBottom: "0.25rem" }}>
              Preview your recording before submitting
              {mode === "record" && seconds > 0 ? ` (${seconds}s)` : ""}:
            </div>
            {sampleUrl && <audio data-testid="sample-playback" controls src={sampleUrl} style={{ width: "100%" }} />}
            {mode === "record" && seconds > 0 && seconds < MIN_SECONDS && (
              <div style={{ color: "#856404", fontSize: "0.85rem", marginTop: "0.4rem" }}>
                That was only {seconds}s — please record at least {MIN_SECONDS} seconds.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Name + submit */}
      <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem", marginBottom: "1.5rem" }}>
        <h3 style={{ marginTop: 0 }}>3. Name &amp; create</h3>
        <input
          type="text"
          data-testid="voice-name-input"
          placeholder="Display name, e.g. Mrs. Rao's Teaching Voice"
          value={voiceName}
          onChange={(e) => setVoiceName(e.target.value)}
          style={{ width: "100%", padding: "0.6rem", borderRadius: "6px", border: "1px solid #ced4da", marginBottom: "1rem", boxSizing: "border-box" }}
        />
        {limitReached && (
          <div style={{ color: "#856404", fontSize: "0.9rem", marginBottom: "0.75rem" }}>
            You have reached the maximum of {maxProfiles} voice profiles. Revoke or delete one to add another.
          </div>
        )}
        <button
          type="button"
          data-testid="create-voice-button"
          onClick={handleCreate}
          disabled={!canSubmit}
          style={{
            padding: "0.7rem 1.4rem",
            background: canSubmit ? "#0d6efd" : "#adb5bd",
            color: "#fff",
            border: "none",
            borderRadius: "6px",
            fontWeight: "bold",
            cursor: canSubmit ? "pointer" : "not-allowed",
          }}
        >
          {submitting ? "Creating voice..." : "Create my cloned voice"}
        </button>
        {!consentChecked && (
          <span style={{ marginLeft: "0.75rem", color: "#6c757d", fontSize: "0.85rem" }}>
            Tick the consent box to enable this button.
          </span>
        )}
      </div>

      {/* Profile list */}
      <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem" }}>
        <h3 style={{ marginTop: 0 }}>Your voice profiles</h3>
        {loading ? (
          <p style={{ color: "#666" }}>Loading...</p>
        ) : profiles.length === 0 ? (
          <p style={{ color: "#666" }} data-testid="no-profiles">You have no voice profiles yet.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0 }} data-testid="voice-profile-list">
            {profiles.map((p) => {
              const style = STATUS_STYLES[p.status] || STATUS_STYLES.pending;
              return (
                <li
                  key={p.id}
                  style={{ border: "1px solid #dee2e6", borderRadius: "8px", padding: "1rem", marginBottom: "0.75rem" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
                    <div>
                      <div style={{ fontWeight: 600 }}>{p.voice_name}</div>
                      <div style={{ fontSize: "0.85rem", color: "#6c757d" }}>
                        {p.teacher_name}
                        {p.languages ? ` • ${p.languages}` : ""}
                      </div>
                    </div>
                    <span
                      data-testid={`status-${p.status}`}
                      style={{ background: style.bg, color: style.color, padding: "0.2rem 0.6rem", borderRadius: "12px", fontSize: "0.8rem", fontWeight: "bold" }}
                    >
                      {p.status}
                    </span>
                  </div>
                  {p.consent_confirmed && p.status === "active" && (
                    <div style={{ fontSize: "0.8rem", color: "#2e7d32", marginTop: "0.4rem" }}>
                      🏷️ AI-generated voice, authorized by the teacher.
                    </div>
                  )}
                  <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      data-testid={`preview-${p.id}`}
                      onClick={() => handlePreview(p.id)}
                      disabled={p.status !== "active" || previewId === p.id}
                      style={{ padding: "0.4rem 0.8rem", background: "#0d6efd", color: "#fff", border: "none", borderRadius: "4px", cursor: p.status === "active" ? "pointer" : "not-allowed", opacity: p.status === "active" ? 1 : 0.6 }}
                    >
                      {previewId === p.id ? "Generating..." : "🔊 Preview voice"}
                    </button>
                    {p.status !== "revoked" && (
                      <button
                        type="button"
                        data-testid={`revoke-${p.id}`}
                        onClick={() => handleRevoke(p)}
                        style={{ padding: "0.4rem 0.8rem", background: "#ffc107", color: "#000", border: "none", borderRadius: "4px", cursor: "pointer" }}
                      >
                        Revoke
                      </button>
                    )}
                    <button
                      type="button"
                      data-testid={`delete-${p.id}`}
                      onClick={() => handleDelete(p)}
                      style={{ padding: "0.4rem 0.8rem", background: "#dc3545", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                    >
                      Delete
                    </button>
                  </div>
                  {p.id === previewAudioId && previewId === null && previewAudio && (
                    <div style={{ marginTop: "0.75rem" }}>
                      <AudioPlayer
                        audioBase64={previewAudio.audio_base64}
                        contentType={previewAudio.content_type || "audio/wav"}
                        isCloned={true}
                        isMock={previewAudio.is_mock}
                        label={previewAudio.label}
                        autoPlay={true}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};

export default TeacherVoicePage;
