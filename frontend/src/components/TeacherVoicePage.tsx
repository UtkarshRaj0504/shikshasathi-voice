import React, { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { AudioPlayer } from "./AudioPlayer";
import { blobToWav } from "../utils/audio";

const READING_SCRIPT =
  "Please read this aloud in a calm, natural voice for about 20 seconds: " +
  "\u201CToday we are going to learn something new together. Take your time, read " +
  "carefully, and think about each idea step by step. If something is not clear, " +
  "we will go over it again slowly, with a simple example, until it makes sense. " +
  "Learning becomes easy when we practise a little every single day.\u201D";

const MIN_SECONDS = 5;
const MAX_SECONDS = 25;

const USABLE_STATUSES = ["active", "pending"];

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

const STATUS_STYLES: Record<string, string> = {
  active: "badge-accent",
  pending: "badge-warning",
  failed: "badge-danger",
  revoked: "badge-muted",
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

  const [mode, setMode] = useState<"record" | "upload">("record");
  const [recording, setRecording] = useState<boolean>(false);
  const [seconds, setSeconds] = useState<number>(0);
  const [level, setLevel] = useState<number>(0);
  const [sampleBlob, setSampleBlob] = useState<Blob | null>(null);
  const [sampleUrl, setSampleUrl] = useState<string | null>(null);
  const [sampleName, setSampleName] = useState<string>("sample.wav");
  const [submitting, setSubmitting] = useState<boolean>(false);

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
      setError(
        !window.isSecureContext
          ? "Microphone access requires a secure HTTPS page. Open ShikshaSaathi over HTTPS, or upload an audio sample instead."
          : "Microphone access was denied or is not supported. Check browser permissions or upload an audio sample instead."
      );
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

  const usableCount = profiles.filter((p) => USABLE_STATUSES.includes(p.status)).length;
  const limitReached = usableCount >= maxProfiles;
  const sampleTooShort = mode === "record" && !!sampleBlob && seconds < MIN_SECONDS;

  const canSubmit =
    consentChecked &&
    !submitting &&
    !!sampleBlob &&
    !!voiceName.trim() &&
    !sampleTooShort &&
    !limitReached;

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
      await loadProfiles();
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

  return (
    <div style={{ maxWidth: 900 }}>
      <h2 style={{ marginTop: 0 }}>🎙️ My Voice</h2>
      <p className="text-muted" style={{ fontSize: "0.92rem", marginBottom: 20 }}>
        Create a safe, authorized copy of your voice so your students can hear study answers
        narrated in your own voice. It is <strong>AI-generated</strong> from a short recording you
        provide, it is clearly labelled to students, and you can revoke or delete it at any time.
      </p>

      {error && (
        <div data-testid="voice-error" className="banner banner-danger">
          ⚠️ {error}
        </div>
      )}
      {success && (
        <div data-testid="voice-success" className="banner banner-success">
          ✅ {success}
        </div>
      )}

      {/* Consent */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>1. Consent</h3>
        <div
          data-testid="consent-text"
          className="surface"
          style={{ padding: 16, maxHeight: 220, overflowY: "auto", whiteSpace: "pre-wrap", fontSize: "0.88rem", lineHeight: 1.55, color: "var(--color-text-muted)" }}
        >
          {consentText || "Loading consent statement..."}
        </div>
        <label style={{ display: "flex", alignItems: "flex-start", gap: 8, marginTop: 12, cursor: "pointer", fontWeight: 500 }}>
          <input
            type="checkbox"
            data-testid="consent-checkbox"
            checked={consentChecked}
            onChange={(e) => setConsentChecked(e.target.checked)}
            className="checkbox"
            style={{ marginTop: 3 }}
          />
          <span>
            I have read the statement above and I consent to ShikshaSaathi creating an
            AI-generated copy of my voice for my students.
          </span>
        </label>
      </div>

      {/* Record / upload */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>2. Record your voice sample</h3>
        <div className="banner banner-info" style={{ marginBottom: 12 }}>
          <strong>Tips for a clean recording:</strong> sit in a quiet room, turn off music and fans,
          hold the mic a hand-width away, and speak naturally for {MIN_SECONDS}-{MAX_SECONDS} seconds.
        </div>
        <div className="surface" style={{ padding: 12, marginBottom: 12, fontSize: "0.86rem" }}>
          <strong>Suggested reading script:</strong>
          <p style={{ margin: "6px 0 0", color: "var(--color-text-muted)" }}>{READING_SCRIPT}</p>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button
            type="button"
            onClick={() => { resetSample(); setMode("record"); }}
            className={`btn ${mode === "record" ? "btn-primary" : "btn-secondary"}`}
            style={{ padding: "0.4rem 0.8rem" }}
          >
            🎙️ Record in browser
          </button>
          <button
            type="button"
            onClick={() => { resetSample(); setMode("upload"); }}
            className={`btn ${mode === "upload" ? "btn-primary" : "btn-secondary"}`}
            style={{ padding: "0.4rem 0.8rem" }}
          >
            📁 Upload WAV / MP3
          </button>
        </div>

        {mode === "record" ? (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {!recording ? (
                <button type="button" data-testid="start-recording" onClick={startRecording} className="btn btn-primary">
                  ● Start recording
                </button>
              ) : (
                <button type="button" data-testid="stop-recording" onClick={stopRecording} className="btn btn-danger">
                  ⏹ Stop ({seconds}s)
                </button>
              )}
              {recording && <span style={{ color: "var(--color-danger)", fontWeight: 600 }}>Recording... {seconds}s / {MAX_SECONDS}s</span>}
            </div>
            <div style={{ marginTop: 10, background: "var(--color-bg-3)", borderRadius: 2, height: 12, overflow: "hidden", width: 220 }} title="Input level">
              <div style={{ width: `${level}%`, height: "100%", background: level > 70 ? "var(--color-danger)" : "var(--color-accent)", transition: "width 0.1s" }} />
            </div>
          </div>
        ) : (
          <label className="dropzone">
            {sampleBlob && mode === "upload" ? `Selected: ${sampleName}` : "Click to choose a WAV or MP3 file"}
            <input type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" onChange={handleFileUpload} style={{ display: "none" }} />
          </label>
        )}

        {sampleBlob && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: "0.82rem", color: "var(--color-text-muted)", marginBottom: 4 }}>
              Preview your recording before submitting
              {mode === "record" && seconds > 0 ? ` (${seconds}s)` : ""}:
            </div>
            {sampleUrl && <audio data-testid="sample-playback" controls src={sampleUrl} style={{ width: "100%" }} />}
            {mode === "record" && seconds > 0 && seconds < MIN_SECONDS && (
              <div className="banner banner-warning" style={{ marginTop: 8, fontSize: "0.82rem" }}>
                That was only {seconds}s — please record at least {MIN_SECONDS} seconds.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Name + submit */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>3. Name &amp; create</h3>
        <input
          type="text"
          data-testid="voice-name-input"
          placeholder="Display name, e.g. Mrs. Rao's Teaching Voice"
          value={voiceName}
          onChange={(e) => setVoiceName(e.target.value)}
          className="input"
          style={{ marginBottom: 12 }}
        />
        {limitReached && (
          <div className="banner banner-warning" style={{ fontSize: "0.86rem", marginBottom: 10 }}>
            You have reached the maximum of {maxProfiles} voice profiles. Revoke or delete one to add another.
          </div>
        )}
        <button
          type="button"
          data-testid="create-voice-button"
          onClick={handleCreate}
          disabled={!canSubmit}
          className="btn btn-primary"
        >
          {submitting ? "Creating voice..." : "Create my cloned voice"}
        </button>
        {!consentChecked && (
          <span style={{ marginLeft: 12, color: "var(--color-text-dim)", fontSize: "0.82rem" }}>
            Tick the consent box to enable this button.
          </span>
        )}
      </div>

      {/* Profile list */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Your voice profiles</h3>
        {loading ? (
          <div className="profile-loading" role="status" aria-label="Loading voice profiles">
            <span className="skeleton profile-loading-line" />
            <span className="skeleton profile-loading-line profile-loading-line-short" />
          </div>
        ) : profiles.length === 0 ? (
          <p className="text-muted" data-testid="no-profiles">You have no voice profiles yet.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0 }} data-testid="voice-profile-list">
            {profiles.map((p) => {
              const cls = STATUS_STYLES[p.status] || "badge-muted";
              return (
                <li
                  key={p.id}
                  className="list-item"
                  style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="item-name">{p.voice_name}</div>
                      <div className="item-meta">
                        {p.teacher_name}
                        {p.languages ? ` • ${p.languages}` : ""}
                      </div>
                    </div>
                    <span data-testid={`status-${p.status}`} className={`badge ${cls}`}>
                      {p.status}
                    </span>
                  </div>
                  {p.consent_confirmed && p.status === "active" && (
                    <div style={{ fontSize: "0.78rem", color: "var(--color-accent)" }}>
                      <span aria-hidden="true">🏷️</span>{" "}
                      <span>AI-generated voice, authorized by the teacher.</span>
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      data-testid={`preview-${p.id}`}
                      onClick={() => handlePreview(p.id)}
                      disabled={p.status !== "active" || previewId === p.id}
                      className="btn btn-secondary"
                      style={{ padding: "0.4rem 0.7rem", fontSize: "0.82rem", opacity: p.status === "active" ? 1 : 0.5 }}
                    >
                      {previewId === p.id ? "Generating..." : "🔊 Preview voice"}
                    </button>
                    {p.status !== "revoked" && (
                      <button
                        type="button"
                        data-testid={`revoke-${p.id}`}
                        onClick={() => handleRevoke(p)}
                        className="btn btn-ghost"
                        style={{ padding: "0.4rem 0.7rem", fontSize: "0.82rem", color: "var(--color-warning)", borderColor: "var(--color-warning)" }}
                      >
                        Revoke
                      </button>
                    )}
                    <button
                      type="button"
                      data-testid={`delete-${p.id}`}
                      onClick={() => handleDelete(p)}
                      className="btn btn-danger"
                      style={{ padding: "0.4rem 0.7rem", fontSize: "0.82rem" }}
                    >
                      Delete
                    </button>
                  </div>
                  {p.id === previewAudioId && previewId === null && previewAudio && (
                    <div style={{ marginTop: 8 }}>
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
