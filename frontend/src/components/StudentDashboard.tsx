import React, { lazy, Suspense, useEffect, useState, useRef } from "react";
import { api, removeToken } from "../services/api";
import { AudioPlayer } from "./AudioPlayer";
import { Aurora, LogoMark } from "./Aurora";
import { UserMenu } from "./UserMenu";

const PdfReader = lazy(() =>
  import("./PdfReader").then((module) => ({ default: module.PdfReader }))
);

interface StudentDashboardProps {
  onLogout: () => void;
}

interface MessageTurn {
  id: string;
  role: "user" | "assistant";
  question?: string;
  answer?: string;
  sources?: any[];
  grounded?: boolean;
  pageNumber?: number | null;
  audioBase64?: string | null;
  isCloned?: boolean;
  isMock?: boolean;
  fallback?: boolean;
  voiceNotice?: string | null;
  voiceLabel?: string | null;
  audioError?: string | null;
  debug?: any;
  timestamp: string;
}

type StudyStep = "SELECT_MATERIAL" | "CHOOSE_VOICE" | "STUDY_READER";

//: Gnani TTS has a fixed per-request latency floor (~9s) regardless of length,
//: so the answer is split into sentence-aligned parts and each part is played as
//: soon as it is synthesized — audio starts in seconds instead of after the
//: whole answer has been generated.
const SPEECH_PART_CHARS = 700;

function splitAnswerForSpeech(text: string, maxChars: number = SPEECH_PART_CHARS): string[] {
  const clean = (text || "").trim();
  if (!clean) return [];
  if (clean.length <= maxChars) return [clean];

  const parts: string[] = [];
  let remaining = clean;
  while (remaining.length > maxChars) {
    const window = remaining.slice(0, maxChars);
    let splitAt = -1;
    for (const sep of [". ", "! ", "? ", "। ", "\n"]) {
      const idx = window.lastIndexOf(sep);
      if (idx > splitAt) splitAt = idx + 1;
    }
    if (splitAt < maxChars * 0.5) {
      const space = window.lastIndexOf(" ");
      splitAt = space > 0 ? space : maxChars;
    }
    const piece = remaining.slice(0, splitAt).trim();
    if (piece) parts.push(piece);
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) parts.push(remaining);
  return parts;
}

// WAV audio recording helpers
function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

function encodeWAV(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([view], { type: "audio/wav" });
}

const ArrowRight: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" className="arrow" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const StudentDashboard: React.FC<StudentDashboardProps> = ({ onLogout }) => {
  const [user, setUser] = useState<any>(null);

  // Navigation & Flow state
  const [currentStep, setCurrentStep] = useState<StudyStep>("SELECT_MATERIAL");
  const [showVoiceModal, setShowVoiceModal] = useState<boolean>(false);

  // Materials state
  const [subjects, setSubjects] = useState<any[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<any>(null);
  const [chapters, setChapters] = useState<any[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<any>(null);
  const [readyDocument, setReadyDocument] = useState<any>(null);
  const [documentFileData, setDocumentFileData] = useState<ArrayBuffer | null>(null);
  const [documentText, setDocumentText] = useState<string | null>(null);
  const [docLoading, setDocLoading] = useState<boolean>(false);

  // Reader state
  const [readerCurrentPage, setReaderCurrentPage] = useState<number>(1);
  const [readerTotalPages, setReaderTotalPages] = useState<number>(1);

  // Voice & Preference state
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<number | null>(null);
  const [questionLanguage, setQuestionLanguage] = useState<string>("indic-auto");
  const [answerLanguage, setAnswerLanguage] = useState<string>("en");
  const [level, setLevel] = useState<string>("intermediate");

  // Voice recording & query state
  const [recording, setRecording] = useState<boolean>(false);
  const [seconds, setSeconds] = useState<number>(0);
  const [transcribing, setTranscribing] = useState<boolean>(false);
  const [transcript, setTranscript] = useState<string>("");
  const [detectedLanguage, setDetectedLanguage] = useState<string | null>(null);
  const [asking, setAsking] = useState<boolean>(false);
  const [ttsLoading, setTtsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Keep only the current exchange; each new question replaces the previous one.
  const [latestExchange, setLatestExchange] = useState<MessageTurn[]>([]);
  const [sampleAudio, setSampleAudio] = useState<{
    base64: string | null;
    contentType?: string;
    isMock?: boolean;
    label?: string | null;
  } | null>(null);
  const [sampleLoadingId, setSampleLoadingId] = useState<number | null>(null);
  const [latestAudio, setLatestAudio] = useState<{
    segments: string[];
    contentType?: string;
    isCloned: boolean;
    isMock?: boolean;
    fallback: boolean;
    notice: string | null;
    label: string | null;
    error?: string | null;
    streaming?: boolean;
  } | null>(null);

  // Identifies the newest question; an older in-flight request must not overwrite it.
  const askRequestIdRef = useRef(0);

  // Audio refs
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const audioInputBuffersRef = useRef<Float32Array[]>([]);
  const timerRef = useRef<any>(null);

  // Initial load: User, Subjects, Voices, Preferences
  useEffect(() => {
    api.getMe()
      .then((u) => setUser(u))
      .catch(() => handleLogout());

    loadInitialData();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (audioContextRef.current && audioContextRef.current.state !== "closed") {
        audioContextRef.current.close().catch(() => {});
      }
    };
  }, []);

  const loadInitialData = async () => {
    try {
      const [subjList, voiceList, prefs] = await Promise.all([
        api.getSubjects(),
        api.getVoices().catch(() => []),
        api.getPreferences().catch(() => ({ voice_profile_id: null, question_language: "indic-auto", answer_language: "en", level: "intermediate" })),
      ]);

      setSubjects(subjList || []);
      setVoices(voiceList || []);
      if (prefs) {
        setSelectedVoiceId(prefs.voice_profile_id || null);
        if (prefs.question_language) setQuestionLanguage(prefs.question_language);
        if (prefs.answer_language) setAnswerLanguage(prefs.answer_language);
      }
    } catch (err: any) {
      console.error("Initialization error:", err);
      setError(err.message || "Failed to load study data.");
    }
  };

  const handleLogout = () => {
    removeToken();
    onLogout();
  };

  const handleSelectSubject = async (subject: any) => {
    setSelectedSubject(subject);
    setSelectedChapter(null);
    setChapters([]);
    setReadyDocument(null);
    setError(null);

    try {
      const chaps = await api.getChapters(subject.id);
      setChapters(chaps);
      if (chaps.length === 0) {
        setError("This subject has no chapters with processed study materials yet.");
      }
    } catch (err: any) {
      setError(err.message || "Failed to load chapters.");
    }
  };

  const handleSelectChapter = (chapter: any) => {
    setSelectedChapter(chapter);
    setError(null);
  };

  const handleProceedToVoiceSelection = () => {
    if (!selectedChapter) {
      setError("Please select a chapter to continue.");
      return;
    }
    setError(null);
    setCurrentStep("CHOOSE_VOICE");
  };

  const handleSaveVoiceAndOpenReader = async (voiceId: number | null) => {
    setSelectedVoiceId(voiceId);
    try {
      await api.updatePreferences({
        voice_profile_id: voiceId,
        question_language: questionLanguage,
        answer_language: answerLanguage,
      });
    } catch (err: any) {
      console.warn("Could not persist voice preference:", err);
    }
    setShowVoiceModal(false);
    openReaderForChapter(selectedChapter);
  };

  const handleQuestionLanguageChange = async (lang: string) => {
    setQuestionLanguage(lang);
    try {
      await api.updatePreferences({
        voice_profile_id: selectedVoiceId,
        question_language: lang,
        answer_language: answerLanguage,
      });
    } catch (err: any) {
      console.warn("Could not persist question language preference:", err);
    }
  };

  const openReaderForChapter = async (chapter: any) => {
    setCurrentStep("STUDY_READER");
    setDocLoading(true);
    setReadyDocument(null);
    setDocumentFileData(null);
    setDocumentText(null);
    setError(null);

    try {
      const docs = await api.getDocuments(chapter.id);
      const readyDoc = docs.find((d: any) => d.status === "ready");
      if (!readyDoc) {
        throw new Error("No ready document found for this chapter.");
      }
      setReadyDocument(readyDoc);

      const isPdf = readyDoc.filename.toLowerCase().endsWith(".pdf");
      const fileBuffer = await api.fetchDocumentFile(readyDoc.id);

      if (isPdf) {
        setDocumentFileData(fileBuffer);
      } else {
        const textDecoder = new TextDecoder("utf-8");
        const content = textDecoder.decode(fileBuffer);
        setDocumentText(content);
      }
    } catch (err: any) {
      console.error("Document reader load error:", err);
      setError(err.message || "Failed to load document for reading.");
    } finally {
      setDocLoading(false);
    }
  };

  const startRecording = async () => {
    setError(null);
    cancelPendingSpeech();
    audioInputBuffersRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      audioStreamRef.current = stream;

      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      const audioContext = new AudioContextClass();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        audioInputBuffersRef.current.push(new Float32Array(inputData));
      };

      source.connect(processor);
      processor.connect(audioContext.destination);

      setRecording(true);
      setSeconds(0);
      timerRef.current = setInterval(() => {
        setSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err: any) {
      console.error("Mic access denied:", err);
      setError(
        !window.isSecureContext
          ? "Microphone access requires a secure HTTPS page. Open ShikshaSaathi over HTTPS, or use a supported localhost address."
          : "Microphone access was denied or is not supported. Check browser permissions, or try again using HTTPS."
      );
    }
  };

  const stopRecording = async () => {
    if (!recording) return;

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setRecording(false);

    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
    }

    if (audioContextRef.current && audioInputBuffersRef.current.length > 0) {
      const inputRate = audioContextRef.current.sampleRate;
      await audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;

      let totalLen = 0;
      for (const b of audioInputBuffersRef.current) totalLen += b.length;
      const merged = new Float32Array(totalLen);
      let offset = 0;
      for (const b of audioInputBuffersRef.current) {
        merged.set(b, offset);
        offset += b.length;
      }

      const wavBlob = encodeWAV(merged, inputRate);

      await handleProcessVoiceQuestion(wavBlob);
    }
  };

  const handleProcessVoiceQuestion = async (audioBlob: Blob) => {
    setTranscribing(true);
    setError(null);

    let transcribedText = "";
    try {
      const sttRes = await api.transcribeAudio(audioBlob, questionLanguage);
      transcribedText = (sttRes.transcript || "").trim();
      setTranscript(transcribedText);
      setDetectedLanguage(sttRes.language || null);
    } catch (err: any) {
      console.error("Transcription error:", err);
      setError(err.message || "Failed to transcribe voice question.");
      setTranscribing(false);
      return;
    } finally {
      setTranscribing(false);
    }

    if (!transcribedText) {
      setError("No speech was recognized. Please speak clearly into the microphone.");
      return;
    }

    await executeAskQuestion(transcribedText);
  };

  const executeAskQuestion = async (queryText: string) => {
    if (!queryText.trim() || !selectedChapter) return;

    const requestId = ++askRequestIdRef.current;

    setAsking(true);
    setError(null);

    let res: any;
    try {
      res = await api.askQuestion(
        queryText,
        selectedChapter.id,
        answerLanguage,
        level,
        readerCurrentPage
      );
    } catch (err: any) {
      if (requestId !== askRequestIdRef.current) return;
      console.error("Ask query error:", err);
      setError(err.message || "Failed to generate answer from study materials.");
      setAsking(false);
      return;
    }
    if (requestId !== askRequestIdRef.current) return;
    setAsking(false);

    const askAnswer: string = res.answer;
    const askSources: any[] = res.sources || [];
    const isGrounded: boolean = res.grounded;
    const askDebug: any = res.debug || null;

    const userTurn: MessageTurn = {
      id: "u_" + Date.now(),
      role: "user",
      question: queryText,
      pageNumber: readerCurrentPage,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    const assistantTurn: MessageTurn = {
      id: "a_" + Date.now(),
      role: "assistant",
      answer: askAnswer,
      sources: askSources,
      grounded: isGrounded,
      pageNumber: readerCurrentPage,
      audioBase64: null,
      isCloned: false,
      isMock: false,
      fallback: false,
      voiceNotice: null,
      voiceLabel: null,
      audioError: null,
      debug: askDebug,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setLatestExchange([userTurn, assistantTurn]);
    setLatestAudio({
      segments: [],
      contentType: "audio/wav",
      isCloned: false,
      isMock: false,
      fallback: false,
      notice: null,
      label: null,
      error: null,
      streaming: true,
    });
    setTtsLoading(true);

    try {
      const result = await synthesizeAnswerInParts(askAnswer, requestId);
      if (!result) return;
      const { meta } = result;
      if (meta) {
        setLatestExchange((prev) =>
          prev.map((msg) =>
            msg.id === assistantTurn.id
              ? {
                  ...msg,
                  audioBase64: result.segments[0] ?? null,
                  isCloned: meta.is_cloned,
                  isMock: meta.is_mock,
                  fallback: meta.fallback,
                  voiceNotice: meta.notice,
                  voiceLabel: meta.label,
                  audioError: null,
                }
              : msg
          )
        );
      }
    } catch (err: any) {
      if (requestId !== askRequestIdRef.current) return;
      console.warn("TTS speak generation warning:", err);
      const ttsError = err.message || "Failed to synthesize speech audio.";
      setLatestAudio((prev) => ({
        segments: prev?.segments ?? [],
        contentType: prev?.contentType || "audio/wav",
        isCloned: prev?.isCloned ?? false,
        isMock: prev?.isMock,
        fallback: prev?.fallback ?? false,
        notice: prev?.notice ?? null,
        label: prev?.label ?? null,
        error: ttsError,
        streaming: false,
      }));
      setLatestExchange((prev) =>
        prev.map((msg) => (msg.id === assistantTurn.id ? { ...msg, audioError: ttsError } : msg))
      );
    } finally {
      if (requestId === askRequestIdRef.current) setTtsLoading(false);
    }
  };

  const synthesizeAnswerInParts = async (
    answerText: string,
    requestId: number
  ): Promise<{ segments: string[]; meta: any } | null> => {
    const parts = splitAnswerForSpeech(answerText);

    if (parts.length === 0) {
      setLatestAudio({
        segments: [],
        contentType: "audio/wav",
        isCloned: false,
        isMock: false,
        fallback: false,
        notice: null,
        label: null,
        error: "There is no speakable text in this answer.",
        streaming: false,
      });
      return { segments: [], meta: null };
    }

    const segments: string[] = [];
    let meta: any = null;

    for (let i = 0; i < parts.length; i++) {
      const ttsRes = await api.speakText(parts[i], selectedVoiceId, answerLanguage);
      if (requestId !== askRequestIdRef.current) return null;
      meta = ttsRes;
      segments.push(ttsRes.audio_base64);
      setLatestAudio({
        segments: [...segments],
        contentType: ttsRes.content_type || "audio/wav",
        isCloned: ttsRes.is_cloned,
        isMock: ttsRes.is_mock,
        fallback: ttsRes.fallback,
        notice: ttsRes.notice,
        label: ttsRes.label,
        error: null,
        streaming: i !== parts.length - 1,
      });
    }

    return { segments, meta };
  };

  const cancelPendingSpeech = () => {
    askRequestIdRef.current += 1;
    setTtsLoading(false);
    setLatestAudio((prev) => (prev ? { ...prev, streaming: false } : prev));
  };

  const getVoiceName = (voiceId: number | null) => {
    if (voiceId === null) return "Default Educational Voice";
    const v = voices.find((item) => item.id === voiceId);
    return v ? `${v.teacher_name} (${v.voice_name})` : "Default Educational Voice";
  };

  const playVoiceSample = async (v: any) => {
    setError(null);
    setSampleLoadingId(v.id);
    try {
      const res = await api.previewVoiceProfile(v.id);
      setSampleAudio({
        base64: res.audio_base64,
        contentType: res.content_type || "audio/wav",
        isMock: res.is_mock,
        label: res.label,
      });
    } catch (err: any) {
      setError(err.message || "Could not play the voice sample.");
    } finally {
      setSampleLoadingId(null);
    }
  };

  const formatSec = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Shared header for all steps
  const AppHeader = ({ title, subtitle, back }: { title: string; subtitle?: string; back?: () => void }) => (
    <header className="app-header">
      <div className="header-left">
        <LogoMark size={24} />
        <div style={{ minWidth: 0 }}>
          <div className="app-title">{title}</div>
          {subtitle && <div className="app-subtitle">{subtitle}</div>}
        </div>
      </div>
      <div className="header-right">
        <UserMenu name={user?.name} role="Student" onLogout={handleLogout} />
        {back && (
          <button className="btn btn-ghost" onClick={back}>← Chapters</button>
        )}
      </div>
    </header>
  );

  // ==========================================
  // RENDER STEP 1: Subject & Chapter Selection
  // ==========================================
  if (currentStep === "SELECT_MATERIAL") {
    return (
      <div className="app-shell">
        <Aurora dim />
        <AppHeader title="ShikshaSaathi Student Voice Portal" subtitle={user ? `Logged in as ${user.name}` : undefined} />
        <main style={{ flex: 1, padding: "32px 24px", overflowY: "auto" }}>
          <div style={{ maxWidth: 800, margin: "0 auto" }}>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>📚 Choose Study Material</h3>
              <p className="text-muted" style={{ fontSize: "0.9rem", marginBottom: 20 }}>
                Select a subject and chapter to start your voice-guided interactive learning session. Only chapters with verified study materials are listed.
              </p>

              {error && <div className="banner banner-danger" role="alert">{error}</div>}

              <div className="field">
                <label className="field-label">1. Select Subject</label>
                <select
                  className="select"
                  value={selectedSubject?.id || ""}
                  onChange={(e) => {
                    const s = subjects.find((sub) => sub.id === Number(e.target.value));
                    if (s) handleSelectSubject(s);
                    else {
                      setSelectedSubject(null);
                      setChapters([]);
                      setSelectedChapter(null);
                    }
                  }}
                >
                  <option value="">-- Choose a Subject --</option>
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>

              {selectedSubject && (
                <div className="field">
                  <label className="field-label">2. Select Chapter</label>
                  {chapters.length === 0 ? (
                    <div className="surface" style={{ padding: 16, color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
                      No chapters with ready study materials available in {selectedSubject.name}.
                    </div>
                  ) : (
                    <div style={{ display: "grid", gap: 8 }}>
                      {chapters.map((chap) => {
                        const isSelected = selectedChapter?.id === chap.id;
                        return (
                          <div
                            key={chap.id}
                            onClick={() => handleSelectChapter(chap)}
                            className={`list-item${isSelected ? " active" : ""}`}
                          >
                            <div>
                              <div className="item-name">Chapter {chap.order}: {chap.title}</div>
                              <div className="item-meta">Verified ready study material available</div>
                            </div>
                            <span style={{ color: isSelected ? "var(--color-accent)" : "var(--color-text-dim)" }}>
                              {isSelected ? "✓" : "➔"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <button
                onClick={handleProceedToVoiceSelection}
                disabled={!selectedChapter}
                className="btn btn-primary w-full"
              >
                Continue to Choose Teacher Voice <ArrowRight />
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ==========================================
  // RENDER STEP 2: Choose Teacher Voice Step
  // ==========================================
  if (currentStep === "CHOOSE_VOICE") {
    return (
      <div className="app-shell">
        <Aurora dim />
        <AppHeader
          title="Step 2: Choose Teacher Voice"
          subtitle={user ? `Logged in as ${user.name}` : undefined}
        />
        <main style={{ flex: 1, padding: "32px 24px", overflowY: "auto" }}>
          <div style={{ maxWidth: 800, margin: "0 auto" }}>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Choose How Your AI Tutor Speaks</h3>
              <p className="text-muted" style={{ fontSize: "0.9rem", marginBottom: 20 }}>
                Select your preferred voice for answers. You can choose the default standard voice or an authorized cloned voice from teachers who have explicitly granted consent.
              </p>

              <div style={{ display: "grid", gap: 12, marginBottom: 24 }}>
                <div
                  onClick={() => setSelectedVoiceId(null)}
                  className={`voice-card${selectedVoiceId === null ? " active" : ""}`}
                >
                  <div>
                    <div className="item-name">🤖 Default AI Voice (Standard)</div>
                    <div className="item-meta">Clear, natural, multilingual educational voice tuned for easy comprehension.</div>
                  </div>
                  <span className="badge badge-accent">{selectedVoiceId === null ? "Selected" : "Choose"}</span>
                </div>

                {voices.map((v) => {
                  const isSelected = selectedVoiceId === v.id;
                  return (
                    <div
                      key={v.id}
                      onClick={() => setSelectedVoiceId(v.id)}
                      className={`voice-card${isSelected ? " active" : ""}`}
                    >
                      <div>
                        <div className="item-name">👨‍🏫 {v.teacher_name}'s Voice</div>
                        <div className="item-meta">
                          Voice Profile: <em>{v.voice_name}</em> • AI-generated voice, authorized by the teacher.
                        </div>
                        <span className="badge badge-accent" style={{ marginTop: 6 }}>
                          Authorized Cloned Voice
                        </span>
                      </div>
                      <button
                        type="button"
                        data-testid={`sample-voice-${v.id}`}
                        onClick={(e) => { e.stopPropagation(); playVoiceSample(v); }}
                        disabled={sampleLoadingId === v.id}
                        className="btn btn-secondary"
                        style={{ padding: "0.35rem 0.7rem", fontSize: "0.8rem" }}
                      >
                        {sampleLoadingId === v.id ? "Loading..." : "🔊 Sample"}
                      </button>
                    </div>
                  );
                })}
              </div>

              {sampleAudio && (
                <div style={{ marginBottom: 16 }}>
                  <AudioPlayer
                    audioBase64={sampleAudio.base64}
                    contentType={sampleAudio.contentType || "audio/wav"}
                    isCloned={true}
                    isMock={sampleAudio.isMock}
                    label={sampleAudio.label}
                    autoPlay={true}
                  />
                </div>
              )}

              <button
                onClick={() => handleSaveVoiceAndOpenReader(selectedVoiceId)}
                className="btn btn-primary w-full"
              >
                Save Preference & Open Study Reader 📖
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ==========================================
  // RENDER STEP 3: Study Reader & Voice Tutor
  // ==========================================
  const latestAssistant = latestExchange.find((turn) => turn.role === "assistant");

  return (
    <div className="app-shell">
      <Aurora dim />
      <header className="app-header">
        <div className="header-left">
          <LogoMark size={24} />
          <div style={{ minWidth: 0 }}>
            <div className="app-title">
              {selectedSubject?.name} • Chapter {selectedChapter?.order}: {selectedChapter?.title}
            </div>
            {readyDocument && (
              <div className="app-subtitle">
                📄 {readyDocument.filename} {readyDocument.filename.toLowerCase().endsWith(".pdf") ? `(Page ${readerCurrentPage} of ${readerTotalPages})` : ""}
              </div>
            )}
          </div>
        </div>
        <div className="header-right">
          <span className="badge badge-muted">
            🎙️ Voice: <strong style={{ color: "var(--color-text)" }}>{getVoiceName(selectedVoiceId)}</strong>
          </span>
          <button className="btn btn-ghost" onClick={() => setShowVoiceModal(true)}>Change</button>
          <UserMenu name={user?.name} role="Student" onLogout={handleLogout} />
        </div>
      </header>

      {/* Voice Switcher Modal */}
      {showVoiceModal && (
        <div className="modal-overlay" onClick={() => setShowVoiceModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Change Tutor Voice</h3>
            <p className="text-muted" style={{ fontSize: "0.88rem", marginBottom: 16 }}>
              Select the voice you want to hear for this study session:
            </p>
            <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
              <div
                onClick={() => handleSaveVoiceAndOpenReader(null)}
                className={`voice-card${selectedVoiceId === null ? " active" : ""}`}
              >
                <strong>🤖 Default Educational Voice</strong>
              </div>
              {voices.map((v) => (
                <div
                  key={v.id}
                  onClick={() => handleSaveVoiceAndOpenReader(v.id)}
                  className={`voice-card${selectedVoiceId === v.id ? " active" : ""}`}
                >
                  <div>
                    <strong>👨‍🏫 {v.teacher_name}'s Voice</strong> ({v.voice_name})
                    <div className="item-meta" style={{ marginTop: 4 }}>Authorized Cloned Voice</div>
                  </div>
                  <button
                    type="button"
                    data-testid={`modal-sample-voice-${v.id}`}
                    onClick={(e) => { e.stopPropagation(); playVoiceSample(v); }}
                    disabled={sampleLoadingId === v.id}
                    className="btn btn-secondary"
                    style={{ padding: "0.3rem 0.6rem", fontSize: "0.75rem" }}
                  >
                    {sampleLoadingId === v.id ? "Loading..." : "🔊 Sample"}
                  </button>
                </div>
              ))}
            </div>
            <button className="btn btn-ghost" onClick={() => setShowVoiceModal(false)}>Close</button>
          </div>
        </div>
      )}

      <div className="study-layout">
        {/* Document Reader Container */}
        <div className="reader-col">
          {docLoading && (
            <div className="document-loading" role="status" aria-label="Loading study material">
              <span className="skeleton document-loading-page" aria-hidden="true" />
              <span>Loading study material…</span>
            </div>
          )}

          {!docLoading && documentFileData && (
            <div className="pdf-frame">
              <Suspense
                fallback={
                  <div className="pdf-loading" role="status">
                    <span className="skeleton pdf-loading-page" aria-hidden="true" />
                    <span>Preparing the PDF reader...</span>
                  </div>
                }
              >
                <PdfReader
                  fileData={documentFileData}
                  initialPage={1}
                  onPageChange={(curr, total) => {
                    setReaderCurrentPage(curr);
                    setReaderTotalPages(total);
                  }}
                />
              </Suspense>
            </div>
          )}

          {!docLoading && documentText && (
            <div style={{ flex: 1, padding: 32, overflowY: "auto", background: "#fff", color: "#1a1a1a", lineHeight: 1.7, fontSize: "1.05rem" }}>
              <div style={{ maxWidth: 700, margin: "0 auto", whiteSpace: "pre-wrap" }}>
                {documentText}
              </div>
            </div>
          )}
        </div>

        {/* Voice Tutor */}
        <div className="tutor-col">
          <h3 style={{ margin: "0 0 4px" }}>🎙️ Ask AI Tutor by Voice</h3>
          <p className="text-muted" style={{ fontSize: "0.82rem", margin: "0 0 16px" }}>
            Press record to speak your question. The tutor uses your open chapter (and active page {readerCurrentPage}) to generate grounded answers.
          </p>

          {/* Language & Level Selectors */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">I Will Speak In (Question Language)</label>
              <select
                data-testid="question-language-select"
                className="select"
                value={questionLanguage}
                onChange={(e) => handleQuestionLanguageChange(e.target.value)}
              >
                <option value="indic-auto">Auto-detect (match my voice)</option>
                <option value="en">English</option>
                <option value="hi">Hindi (हिन्दी)</option>
                <option value="kn">Kannada (ಕನ್ನಡ)</option>
                <option value="ta">Tamil (தமிழ்)</option>
                <option value="te">Telugu (తెలుగు)</option>
                <option value="mr">Marathi (मराठी)</option>
                <option value="gu">Gujarati (ગુજરાતી)</option>
                <option value="bn">Bengali (বাংলা)</option>
                <option value="ml">Malayalam (മലയാളം)</option>
                <option value="pa">Punjabi (ਪੰਜਾਬੀ)</option>
              </select>
            </div>

            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">Answer Language (Tutor's Reply)</label>
              <select
                className="select"
                value={answerLanguage}
                onChange={(e) => setAnswerLanguage(e.target.value)}
              >
                <option value="en">English</option>
                <option value="indic-auto">Auto-detect (Match my voice)</option>
                <option value="kn-IN">Kannada (ಕನ್ನಡ)</option>
                <option value="hi-IN">Hindi (हिन्दी)</option>
                <option value="ta-IN">Tamil (தமிழ்)</option>
                <option value="te-IN">Telugu (తెలుగు)</option>
                <option value="mr-IN">Marathi (मराठी)</option>
                <option value="gu-IN">Gujarati (ગુજરાતી)</option>
                <option value="bn-IN">Bengali (বাংলা)</option>
                <option value="ml-IN">Malayalam (മലയാളം)</option>
                <option value="pa-IN">Punjabi (ਪੰਜਾਬੀ)</option>
                <option value="as-IN">Assamese (অসমীয়া)</option>
              </select>
            </div>
          </div>

          <div className="field">
            <label className="field-label">Explanation Level</label>
            <select
              className="select"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
            >
              <option value="beginner">Beginner (Simple & examples)</option>
              <option value="intermediate">Intermediate (Standard)</option>
              <option value="advanced">Advanced (Deep technical)</option>
            </select>
          </div>

          {/* Sticky voice panel */}
          <div className="voice-panel">
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
              <button
                onClick={recording ? stopRecording : startRecording}
                disabled={transcribing || asking}
                className={`mic-button${recording ? " recording" : ""}`}
                aria-label={recording ? "Stop recording" : "Start recording"}
              >
                {recording ? "⏹" : "🎙"}
              </button>
              <div style={{ flex: 1, minWidth: 0 }}>
                {recording ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span className="badge badge-danger">● Recording {formatSec(seconds)}</span>
                    <div className="level-bars" aria-hidden="true">
                      {Array.from({ length: 12 }).map((_, i) => <span key={i} />)}
                    </div>
                  </div>
                ) : (
                  <div className="text-dim" style={{ fontSize: "0.82rem" }}>
                    {transcribing ? "Transcribing..." : asking ? "Generating answer..." : "Press the mic to ask a question"}
                  </div>
                )}
              </div>
            </div>

            {/* Editable Transcript */}
            <div>
              <label className="field-label" style={{ marginBottom: 4 }}>
                Question Transcript (Editable):
                {detectedLanguage && (
                  <span data-testid="detected-language" style={{ marginLeft: 8, fontWeight: 500, color: "var(--color-accent)", fontSize: "0.8rem" }}>
                    Detected language: {detectedLanguage}
                  </span>
                )}
              </label>
              <textarea
                className="textarea"
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder={transcribing ? "Transcribing your voice question..." : "Speak using the mic or type your question here..."}
                rows={3}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button
                  onClick={() => executeAskQuestion(transcript)}
                  disabled={asking || !transcript.trim() || transcribing}
                  className="btn btn-secondary"
                  style={{ padding: "0.4rem 1rem", fontSize: "0.82rem" }}
                >
                  {asking ? "⏳ Generating..." : "✏️ Edit & Resend Question"}
                </button>
              </div>
            </div>
          </div>

          {error && <div className="banner banner-danger" role="alert">⚠️ {error}</div>}

          {/* Latest answer audio player */}
          {latestAudio && (
            <AudioPlayer
              segments={latestAudio.segments}
              contentType={latestAudio.contentType || "audio/wav"}
              isCloned={latestAudio.isCloned}
              isMock={latestAudio.isMock}
              fallback={latestAudio.fallback}
              notice={latestAudio.notice}
              label={latestAudio.label}
              loading={ttsLoading}
              streaming={latestAudio.streaming}
              error={latestAudio.error}
              autoPlay={true}
              onRetry={() => {
                const lastAns = latestExchange.find((turn) => turn.role === "assistant")?.answer;
                if (!lastAns) return;
                const retryId = ++askRequestIdRef.current;
                setTtsLoading(true);
                setLatestAudio({
                  segments: [],
                  contentType: "audio/wav",
                  isCloned: false,
                  isMock: false,
                  fallback: false,
                  notice: null,
                  label: null,
                  error: null,
                  streaming: true,
                });
                synthesizeAnswerInParts(lastAns, retryId)
                  .catch((err: any) => {
                    if (retryId !== askRequestIdRef.current) return;
                    setLatestAudio((prev) => ({
                      segments: prev?.segments ?? [],
                      contentType: prev?.contentType || "audio/wav",
                      isCloned: prev?.isCloned ?? false,
                      isMock: prev?.isMock,
                      fallback: prev?.fallback ?? false,
                      notice: prev?.notice ?? null,
                      label: prev?.label ?? null,
                      error: err.message || "Failed to generate speech audio.",
                      streaming: false,
                    }));
                  })
                  .finally(() => {
                    if (retryId === askRequestIdRef.current) setTtsLoading(false);
                  });
              }}
            />
          )}

          {/* Latest answer card */}
          {latestAssistant && (
            <div className="answer-card">
              <div className="card-head">
                <strong>💡 AI Educational Tutor</strong>
                <span>{latestAssistant.timestamp}</span>
              </div>

              {/* Grounded / Not-Grounded Banner */}
              <div className={`banner ${latestAssistant.grounded ? "banner-success" : "banner-warning"}`} style={{ marginBottom: 12 }}>
                {latestAssistant.grounded
                  ? `✅ Grounded in Study Material (${selectedChapter?.title}${latestAssistant.pageNumber ? ` • Page ${latestAssistant.pageNumber}` : ""})`
                  : "⚠️ Notice: This question isn't covered in the uploaded material."}
              </div>

              {/* Cloned voice badge */}
              {latestAssistant.isCloned && (
                <span className="badge badge-accent" style={{ marginBottom: 8 }}>
                  <span aria-hidden="true">🏷️</span>{" "}
                  <span>{latestAssistant.voiceLabel || "AI-generated voice, authorized by the teacher."}</span>
                </span>
              )}

              <p className="answer-text">{latestAssistant.answer}</p>

              {/* Source chips */}
              {latestAssistant.sources && latestAssistant.sources.length > 0 && (
                <div className="sources-list">
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>📚 Sources Referenced:</div>
                  <ul>
                    {latestAssistant.sources.map((src: any, idx: number) => (
                      <li key={idx} style={{ marginBottom: 4 }}>
                        <strong>{src.document_name}</strong>
                        {src.page_number ? <span className="badge badge-muted" style={{ marginLeft: 6 }}>p. {src.page_number}</span> : null}
                        {src.excerpt ? `: "${src.excerpt}"` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Retrieval debug */}
              {latestAssistant.debug && (
                <details data-testid="rag-debug" style={{ marginTop: 12, borderTop: "1px dashed var(--color-border)", paddingTop: 10, fontSize: "0.78rem", color: "var(--color-text-dim)" }}>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>🐞 Debug (retrieval)</summary>
                  <div style={{ marginTop: 8 }}>
                    <div>
                      Model: <code>{latestAssistant.debug.embedding_model}</code> • Query dim:{" "}
                      <code>{latestAssistant.debug.query_dimension}</code> • Threshold:{" "}
                      <code>{latestAssistant.debug.threshold}</code> • Candidates:{" "}
                      <code>{latestAssistant.debug.candidate_count}</code> • Dim mismatch:{" "}
                      <code>{latestAssistant.debug.dimension_mismatch_chunks}</code>
                    </div>
                    <ol style={{ margin: "8px 0 0", paddingLeft: 20 }}>
                      {(latestAssistant.debug.scored_chunks || []).map((c: any) => (
                        <li key={c.chunk_id}>
                          <code>#{c.chunk_id}</code> {c.doc}
                          {c.page ? ` (p${c.page})` : ""} — score{" "}
                          <strong>{c.score}</strong> (vec {c.vector_score}, kw{" "}
                          {c.keyword_score})
                          {c.content_preview ? `: "${c.content_preview}…"` : ""}
                        </li>
                      ))}
                    </ol>
                  </div>
                </details>
              )}
            </div>
          )}

          {latestExchange.length === 0 && (
            <div style={{ color: "var(--color-text-dim)", fontSize: "0.88rem", textAlign: "center", marginTop: 32 }}>
              No questions asked yet. Ask a question using the microphone above to start learning!
            </div>
          )}
        </div>
      </div>

    </div>
  );
};
