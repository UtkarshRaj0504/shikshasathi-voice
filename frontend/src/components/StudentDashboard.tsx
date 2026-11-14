import React, { useEffect, useState, useRef } from "react";
import { api, removeToken } from "../services/api";
import { PdfReader } from "./PdfReader";
import { AudioPlayer } from "./AudioPlayer";

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

// WAV audio recording helpers
function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

function downsampleBuffer(buffer: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return buffer;
  const sampleRateRatio = inputRate / outputRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
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

  // Latest question & answer (only the most recent exchange is kept)
  const [conversation, setConversation] = useState<MessageTurn[]>([]);
  const [latestAudio, setLatestAudio] = useState<{
    base64: string | null;
    contentType?: string;
    isCloned: boolean;
    isMock?: boolean;
    fallback: boolean;
    notice: string | null;
    label: string | null;
    error?: string | null;
  } | null>(null);

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
        // Load question_language (for STT) - defaults to indic-auto
        if (prefs.question_language) setQuestionLanguage(prefs.question_language);
        // Load answer_language (for TTS and LLM)
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

  // Step 1: Subject & Chapter Selection
  const handleSelectSubject = async (subject: any) => {
    setSelectedSubject(subject);
    setSelectedChapter(null);
    setChapters([]);
    setReadyDocument(null);
    setError(null);

    try {
      // Backend only returns chapters that have at least one ready document for students
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

  // Step 2: Voice Selection
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

  // Persist the student's spoken (question) language so their choice is remembered.
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

  // Step 3: Open Reader
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
        // Plain text / markdown decoding
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

  // Audio Recording Flow (under Reader)
  const startRecording = async () => {
    setError(null);
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
      setError("Microphone access was denied or is not supported. Please check microphone permissions.");
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

      const targetRate = 16000;
      const downsampled = downsampleBuffer(merged, inputRate, targetRate);
      const wavBlob = encodeWAV(downsampled, targetRate);

      // Process voice question automatically
      await handleProcessVoiceQuestion(wavBlob);
    }
  };

  // Flow: Record -> POST /stt/transcribe -> Show transcript -> Auto-call POST /ask -> Auto-call POST /tts/speak
  const handleProcessVoiceQuestion = async (audioBlob: Blob) => {
    setTranscribing(true);
    setError(null);

    let transcribedText = "";
    try {
      const sttRes = await api.transcribeAudio(audioBlob, questionLanguage);
      transcribedText = (sttRes.transcript || "").trim();
      setTranscript(transcribedText);
      // Show the language the STT provider actually detected/used.
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

    // Automatically trigger question answering
    await executeAskQuestion(transcribedText);
  };

  const executeAskQuestion = async (queryText: string) => {
    if (!queryText.trim() || !selectedChapter) return;

    setAsking(true);
    setError(null);

    let askAnswer = "";
    let askSources: any[] = [];
    let isGrounded = false;
    let askDebug: any = null;

    try {
      const res = await api.askQuestion(
        queryText,
        selectedChapter.id,
        answerLanguage,
        level,
        readerCurrentPage
      );

      askAnswer = res.answer;
      askSources = res.sources || [];
      isGrounded = res.grounded;
      askDebug = res.debug || null;
    } catch (err: any) {
      console.error("Ask query error:", err);
      setError(err.message || "Failed to generate answer from study materials.");
      setAsking(false);
      return;
    } finally {
      setAsking(false);
    }

    // Call TTS speak with chosen voice and autoplay
    setTtsLoading(true);
    let audioB64: string | null = null;
    let isCloned = false;
    let isMock = false;
    let fallback = false;
    let notice: string | null = null;
    let label: string | null = null;
    let ttsError: string | null = null;

    try {
      const ttsRes = await api.speakText(askAnswer, selectedVoiceId, answerLanguage);
      audioB64 = ttsRes.audio_base64;
      isCloned = ttsRes.is_cloned;
      isMock = ttsRes.is_mock;
      fallback = ttsRes.fallback;
      notice = ttsRes.notice;
      label = ttsRes.label;

      setLatestAudio({
        base64: audioB64,
        contentType: ttsRes.content_type || "audio/wav",
        isCloned,
        isMock,
        fallback,
        notice,
        label,
        error: null,
      });
    } catch (err: any) {
      console.warn("TTS speak generation warning:", err);
      ttsError = err.message || "Failed to synthesize speech audio.";
      setLatestAudio({
        base64: null,
        isCloned: false,
        isMock: false,
        fallback: false,
        notice: null,
        label: null,
        error: ttsError,
      });
    } finally {
      setTtsLoading(false);
    }

    // Only the latest question and answer are kept: a new answer replaces the previous one.
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
      audioBase64: audioB64,
      isCloned,
      isMock,
      fallback,
      voiceNotice: notice,
      voiceLabel: label,
      audioError: ttsError,
      debug: askDebug,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setConversation([userTurn, assistantTurn]);
  };

  const getVoiceName = (voiceId: number | null) => {
    if (voiceId === null) return "Default Educational Voice";
    const v = voices.find((item) => item.id === voiceId);
    return v ? `${v.teacher_name} (${v.voice_name})` : "Default Educational Voice";
  };

  const formatSec = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // ==========================================
  // RENDER STEP 1: Subject & Chapter Selection
  // ==========================================
  if (currentStep === "SELECT_MATERIAL") {
    return (
      <div style={{ minHeight: "100vh", background: "#f4f6f8", fontFamily: "system-ui, -apple-system, sans-serif" }}>
        {/* Top Header */}
        <header style={{ background: "#fff", borderBottom: "1px solid #dee2e6", padding: "1rem 2rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ margin: 0, color: "#198754" }}>🎓 ShikshaSaathi Student Voice Portal</h2>
            {user && <p style={{ margin: "0.2rem 0 0", color: "#666", fontSize: "0.9rem" }}>Logged in as <strong>{user.name}</strong> (Student)</p>}
          </div>
          <button
            onClick={handleLogout}
            style={{ padding: "0.5rem 1rem", background: "#dc3545", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontWeight: 500 }}
          >
            Sign Out
          </button>
        </header>

        <main style={{ maxWidth: "800px", margin: "2.5rem auto", padding: "0 1.5rem" }}>
          <div style={{ background: "#fff", borderRadius: "12px", padding: "2rem", boxShadow: "0 4px 16px rgba(0,0,0,0.06)" }}>
            <h3 style={{ marginTop: 0, color: "#333" }}>📚 Choose Study Material</h3>
            <p style={{ color: "#666", fontSize: "0.95rem", marginBottom: "1.5rem" }}>
              Select a subject and chapter to start your voice-guided interactive learning session. Only chapters with verified study materials are listed.
            </p>

            {error && (
              <div style={{ background: "#f8d7da", color: "#842029", padding: "0.75rem 1rem", borderRadius: "6px", marginBottom: "1.5rem", border: "1px solid #f5c2c7" }}>
                {error}
              </div>
            )}

            {/* Subject Selector */}
            <div style={{ marginBottom: "1.5rem" }}>
              <label style={{ display: "block", fontWeight: 600, marginBottom: "0.5rem" }}>1. Select Subject</label>
              <select
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
                style={{ width: "100%", padding: "0.75rem", borderRadius: "6px", border: "1px solid #ced4da", fontSize: "1rem" }}
              >
                <option value="">-- Choose a Subject --</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>

            {/* Chapter Selector (only chapters with ready documents) */}
            {selectedSubject && (
              <div style={{ marginBottom: "2rem" }}>
                <label style={{ display: "block", fontWeight: 600, marginBottom: "0.5rem" }}>2. Select Chapter</label>
                {chapters.length === 0 ? (
                  <div style={{ padding: "1rem", background: "#f8f9fa", borderRadius: "6px", color: "#666", fontSize: "0.95rem" }}>
                    No chapters with ready study materials available in {selectedSubject.name}.
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: "0.75rem" }}>
                    {chapters.map((chap) => {
                      const isSelected = selectedChapter?.id === chap.id;
                      return (
                        <div
                          key={chap.id}
                          onClick={() => handleSelectChapter(chap)}
                          style={{
                            padding: "1rem",
                            border: `2px solid ${isSelected ? "#198754" : "#dee2e6"}`,
                            background: isSelected ? "#e8f5e9" : "#fff",
                            borderRadius: "8px",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 600, fontSize: "1.05rem", color: isSelected ? "#198754" : "#212529" }}>
                              Chapter {chap.order}: {chap.title}
                            </div>
                            <div style={{ fontSize: "0.85rem", color: "#666", marginTop: "0.25rem" }}>
                              Verified ready study material available
                            </div>
                          </div>
                          <span style={{ fontSize: "1.2rem" }}>{isSelected ? "✅" : "➔"}</span>
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
              style={{
                width: "100%",
                padding: "0.85rem",
                background: selectedChapter ? "#198754" : "#6c757d",
                color: "#fff",
                border: "none",
                borderRadius: "6px",
                fontWeight: "bold",
                fontSize: "1.05rem",
                cursor: selectedChapter ? "pointer" : "not-allowed",
              }}
            >
              Continue to Choose Teacher Voice ➔
            </button>
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
      <div style={{ minHeight: "100vh", background: "#f4f6f8", fontFamily: "system-ui, -apple-system, sans-serif" }}>
        <header style={{ background: "#fff", borderBottom: "1px solid #dee2e6", padding: "1rem 2rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <button
              onClick={() => setCurrentStep("SELECT_MATERIAL")}
              style={{ background: "none", border: "none", color: "#0d6efd", cursor: "pointer", fontSize: "0.9rem", padding: 0, marginBottom: "0.25rem" }}
            >
              ← Back to Material Selection
            </button>
            <h2 style={{ margin: 0 }}>🎙️ Step 2: Choose Teacher Voice</h2>
          </div>
          <button
            onClick={handleLogout}
            style={{ padding: "0.5rem 1rem", background: "#dc3545", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontWeight: 500 }}
          >
            Sign Out
          </button>
        </header>

        <main style={{ maxWidth: "800px", margin: "2.5rem auto", padding: "0 1.5rem" }}>
          <div style={{ background: "#fff", borderRadius: "12px", padding: "2rem", boxShadow: "0 4px 16px rgba(0,0,0,0.06)" }}>
            <h3 style={{ marginTop: 0, color: "#333" }}>Choose How Your AI Tutor Speaks</h3>
            <p style={{ color: "#666", fontSize: "0.95rem", marginBottom: "1.5rem" }}>
              Select your preferred voice for answers. You can choose the default standard voice or an authorized cloned voice from teachers who have explicitly granted consent.
            </p>

            <div style={{ display: "grid", gap: "1rem", marginBottom: "2rem" }}>
              {/* Option 1: Default Voice */}
              <div
                onClick={() => setSelectedVoiceId(null)}
                style={{
                  padding: "1.2rem",
                  border: `2px solid ${selectedVoiceId === null ? "#0d6efd" : "#dee2e6"}`,
                  background: selectedVoiceId === null ? "#e7f1ff" : "#fff",
                  borderRadius: "8px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: "1.1rem", color: selectedVoiceId === null ? "#0d6efd" : "#212529" }}>
                    🤖 Default AI Voice (Standard)
                  </div>
                  <div style={{ color: "#666", fontSize: "0.85rem", marginTop: "0.3rem" }}>
                    Clear, natural, multilingual educational voice tuned for easy comprehension.
                  </div>
                </div>
                <span style={{ fontSize: "1.3rem" }}>{selectedVoiceId === null ? "🔘" : "⚪"}</span>
              </div>

              {/* Option 2+: Active Teacher Cloned Voices with confirmed consent */}
              {voices.map((v) => {
                const isSelected = selectedVoiceId === v.id;
                return (
                  <div
                    key={v.id}
                    onClick={() => setSelectedVoiceId(v.id)}
                    style={{
                      padding: "1.2rem",
                      border: `2px solid ${isSelected ? "#198754" : "#dee2e6"}`,
                      background: isSelected ? "#e8f5e9" : "#fff",
                      borderRadius: "8px",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                        <span style={{ fontWeight: 600, fontSize: "1.1rem", color: isSelected ? "#198754" : "#212529" }}>
                          👨‍🏫 {v.teacher_name}'s Voice
                        </span>
                        <span style={{ background: "#d1e7dd", color: "#0f5132", fontSize: "0.75rem", padding: "0.2rem 0.5rem", borderRadius: "12px", fontWeight: "bold" }}>
                          Authorized Cloned Voice
                        </span>
                      </div>
                      <div style={{ color: "#666", fontSize: "0.85rem", marginTop: "0.4rem" }}>
                        Voice Profile: <em>{v.voice_name}</em> • AI-generated voice, authorized by the teacher.
                      </div>
                    </div>
                    <span style={{ fontSize: "1.3rem" }}>{isSelected ? "🔘" : "⚪"}</span>
                  </div>
                );
              })}
            </div>

            <button
              onClick={() => handleSaveVoiceAndOpenReader(selectedVoiceId)}
              style={{
                width: "100%",
                padding: "0.85rem",
                background: "#0d6efd",
                color: "#fff",
                border: "none",
                borderRadius: "6px",
                fontWeight: "bold",
                fontSize: "1.05rem",
                cursor: "pointer",
              }}
            >
              Save Preference & Open Study Reader 📖
            </button>
          </div>
        </main>
      </div>
    );
  }

  // ==========================================
  // RENDER STEP 3: Study Reader & Voice Tutor
  // ==========================================
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#f8f9fa", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      {/* Study Page Header with Chapter Info & Voice Switcher */}
      <header
        style={{
          background: "#fff",
          borderBottom: "1px solid #dee2e6",
          padding: "0.75rem 1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          boxShadow: "0 2px 4px rgba(0,0,0,0.04)",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <button
            onClick={() => setCurrentStep("SELECT_MATERIAL")}
            style={{
              padding: "0.4rem 0.8rem",
              background: "#e9ecef",
              border: "1px solid #ced4da",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.85rem",
              fontWeight: 500,
            }}
          >
            ← Chapters
          </button>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#212529" }}>
              {selectedSubject?.name} • Chapter {selectedChapter?.order}: {selectedChapter?.title}
            </h3>
            {readyDocument && (
              <span style={{ fontSize: "0.8rem", color: "#666" }}>
                📄 {readyDocument.filename} {readyDocument.filename.toLowerCase().endsWith(".pdf") ? `(Page ${readerCurrentPage} of ${readerTotalPages})` : ""}
              </span>
            )}
          </div>
        </div>

        {/* Header Voice Indicator with Change Action */}
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              background: "#e7f1ff",
              border: "1px solid #b6d4fe",
              padding: "0.35rem 0.75rem",
              borderRadius: "20px",
              fontSize: "0.85rem",
            }}
          >
            <span>🎙️</span>
            <span>
              Voice: <strong>{getVoiceName(selectedVoiceId)}</strong>
            </span>
            <button
              onClick={() => setShowVoiceModal(true)}
              style={{
                marginLeft: "0.4rem",
                background: "#0d6efd",
                color: "#fff",
                border: "none",
                borderRadius: "12px",
                padding: "0.15rem 0.5rem",
                fontSize: "0.75rem",
                cursor: "pointer",
              }}
            >
              Change
            </button>
          </div>

          <button
            onClick={handleLogout}
            style={{ padding: "0.4rem 0.8rem", background: "#dc3545", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "0.85rem" }}
          >
            Sign Out
          </button>
        </div>
      </header>

      {/* Voice Switcher Modal (accessible from Header) */}
      {showVoiceModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div style={{ background: "#fff", borderRadius: "12px", padding: "1.75rem", maxWidth: "550px", width: "90%", maxHeight: "80vh", overflowY: "auto" }}>
            <h3 style={{ marginTop: 0 }}>Change Tutor Voice</h3>
            <p style={{ color: "#666", fontSize: "0.9rem" }}>Select the voice you want to hear for this study session:</p>
            <div style={{ display: "grid", gap: "0.75rem", margin: "1rem 0 1.5rem" }}>
              <div
                onClick={() => handleSaveVoiceAndOpenReader(null)}
                style={{
                  padding: "0.75rem",
                  border: `2px solid ${selectedVoiceId === null ? "#0d6efd" : "#dee2e6"}`,
                  borderRadius: "6px",
                  cursor: "pointer",
                  background: selectedVoiceId === null ? "#e7f1ff" : "#fff",
                }}
              >
                <strong>🤖 Default Educational Voice</strong>
              </div>
              {voices.map((v) => (
                <div
                  key={v.id}
                  onClick={() => handleSaveVoiceAndOpenReader(v.id)}
                  style={{
                    padding: "0.75rem",
                    border: `2px solid ${selectedVoiceId === v.id ? "#198754" : "#dee2e6"}`,
                    borderRadius: "6px",
                    cursor: "pointer",
                    background: selectedVoiceId === v.id ? "#e8f5e9" : "#fff",
                  }}
                >
                  <strong>👨‍🏫 {v.teacher_name}'s Voice</strong> ({v.voice_name})
                  <div style={{ fontSize: "0.8rem", color: "#198754", marginTop: "0.2rem" }}>Authorized Cloned Voice</div>
                </div>
              ))}
            </div>
            <button
              onClick={() => setShowVoiceModal(false)}
              style={{ padding: "0.5rem 1rem", background: "#6c757d", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Main Split Layout: Left/Top = Document Reader, Right/Bottom = Voice Question Studio */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", flex: 1, overflow: "hidden" }}>
        {/* Document Reader Container */}
        <div style={{ borderRight: "1px solid #dee2e6", display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
          {docLoading && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>
              <p>⏳ Loading document material...</p>
            </div>
          )}

          {!docLoading && documentFileData && (
            <PdfReader
              fileData={documentFileData}
              initialPage={1}
              onPageChange={(curr, total) => {
                setReaderCurrentPage(curr);
                setReaderTotalPages(total);
              }}
            />
          )}

          {!docLoading && documentText && (
            <div style={{ flex: 1, padding: "2rem", overflowY: "auto", background: "#fff", lineHeight: 1.7, fontSize: "1.05rem", color: "#212529" }}>
              <div style={{ maxWidth: "700px", margin: "0 auto", whiteSpace: "pre-wrap" }}>
                {documentText}
              </div>
            </div>
          )}
        </div>

        {/* Voice Tutor & Interactive Question Studio */}
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflowY: "auto", background: "#fff", padding: "1.5rem" }}>
          <h3 style={{ margin: "0 0 0.5rem", color: "#212529" }}>🎙️ Ask AI Tutor by Voice</h3>
          <p style={{ color: "#666", fontSize: "0.85rem", margin: "0 0 1rem" }}>
            Press record to speak your question. The tutor uses your open chapter (and active page {readerCurrentPage}) to generate grounded answers.
          </p>

          {/* Language & Level Selector */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <div>
              <label style={{ fontSize: "0.8rem", fontWeight: 600, display: "block", marginBottom: "0.25rem" }}>
                I Will Speak In (Question Language)
              </label>
              <select
                data-testid="question-language-select"
                value={questionLanguage}
                onChange={(e) => handleQuestionLanguageChange(e.target.value)}
                style={{ width: "100%", padding: "0.4rem", borderRadius: "4px", border: "1px solid #ced4da", fontSize: "0.85rem" }}
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

            <div>
              <label style={{ fontSize: "0.8rem", fontWeight: 600, display: "block", marginBottom: "0.25rem" }}>Answer Language (Tutor's Reply)</label>
              <select
                value={answerLanguage}
                onChange={(e) => setAnswerLanguage(e.target.value)}
                style={{ width: "100%", padding: "0.4rem", borderRadius: "4px", border: "1px solid #ced4da", fontSize: "0.85rem" }}
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

          <div style={{ marginBottom: "1rem" }}>
            <label style={{ fontSize: "0.8rem", fontWeight: 600, display: "block", marginBottom: "0.25rem" }}>Explanation Level</label>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              style={{ width: "100%", padding: "0.4rem", borderRadius: "4px", border: "1px solid #ced4da", fontSize: "0.85rem" }}
            >
              <option value="beginner">Beginner (Simple & examples)</option>
              <option value="intermediate">Intermediate (Standard)</option>
              <option value="advanced">Advanced (Deep technical)</option>
            </select>
          </div>

          {/* Recording & Action Controls */}
          <div style={{ background: "#f8f9fa", border: "1px solid #e9ecef", borderRadius: "8px", padding: "1rem", marginBottom: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "0.75rem" }}>
              {!recording ? (
                <button
                  onClick={startRecording}
                  disabled={transcribing || asking}
                  style={{
                    padding: "0.7rem 1.4rem",
                    background: "#28a745",
                    color: "#fff",
                    border: "none",
                    borderRadius: "24px",
                    fontWeight: "bold",
                    fontSize: "0.95rem",
                    cursor: transcribing || asking ? "not-allowed" : "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    boxShadow: "0 2px 6px rgba(40,167,69,0.3)",
                  }}
                >
                  🎙️ Ask Question
                </button>
              ) : (
                <button
                  onClick={stopRecording}
                  style={{
                    padding: "0.7rem 1.4rem",
                    background: "#dc3545",
                    color: "#fff",
                    border: "none",
                    borderRadius: "24px",
                    fontWeight: "bold",
                    fontSize: "0.95rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    boxShadow: "0 2px 6px rgba(220,53,69,0.3)",
                  }}
                >
                  ⏹️ Stop & Ask ({formatSec(seconds)})
                </button>
              )}

              {recording && (
                <span style={{ color: "#dc3545", fontWeight: 600, fontSize: "0.9rem" }}>
                  ● Recording in progress... speak your question
                </span>
              )}
            </div>

            {/* Editable Transcript Box */}
            <div>
              <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "#495057", display: "block", marginBottom: "0.25rem" }}>
                Question Transcript (Editable):
                {detectedLanguage && (
                  <span
                    data-testid="detected-language"
                    style={{ marginLeft: "0.5rem", fontWeight: 500, color: "#0d6efd", fontSize: "0.8rem" }}
                  >
                    Detected language: {detectedLanguage}
                  </span>
                )}
              </label>
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder={transcribing ? "Transcribing your voice question..." : "Speak using the mic or type your question here..."}
                rows={3}
                style={{ width: "100%", padding: "0.6rem", borderRadius: "6px", border: "1px solid #ced4da", fontSize: "0.95rem", boxSizing: "border-box" }}
              />

              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem" }}>
                <button
                  onClick={() => executeAskQuestion(transcript)}
                  disabled={asking || !transcript.trim() || transcribing}
                  style={{
                    padding: "0.45rem 1rem",
                    background: "#0d6efd",
                    color: "#fff",
                    border: "none",
                    borderRadius: "4px",
                    fontWeight: 600,
                    cursor: asking || !transcript.trim() ? "not-allowed" : "pointer",
                    fontSize: "0.85rem",
                  }}
                >
                  {asking ? "⏳ Generating..." : "✏️ Edit & Resend Question"}
                </button>
              </div>
            </div>
          </div>

          {error && (
            <div style={{ background: "#f8d7da", color: "#842029", padding: "0.75rem", borderRadius: "6px", marginBottom: "1rem", fontSize: "0.9rem" }}>
              ⚠️ {error}
            </div>
          )}

          {/* Autoplay Audio Player for latest answer */}
          {latestAudio && (
            <AudioPlayer
              audioBase64={latestAudio.base64}
              contentType={latestAudio.contentType || "audio/wav"}
              isCloned={latestAudio.isCloned}
              isMock={latestAudio.isMock}
              fallback={latestAudio.fallback}
              notice={latestAudio.notice}
              label={latestAudio.label}
              loading={ttsLoading}
              error={latestAudio.error}
              autoPlay={true}
              onRetry={() => {
                const lastAns = conversation.filter((c) => c.role === "assistant").slice(-1)[0]?.answer;
                if (lastAns) {
                  setTtsLoading(true);
                  api.speakText(lastAns, selectedVoiceId, answerLanguage)
                    .then((res) => {
                      setLatestAudio({
                        base64: res.audio_base64,
                        contentType: res.content_type || "audio/wav",
                        isCloned: res.is_cloned,
                        isMock: res.is_mock,
                        fallback: res.fallback,
                        notice: res.notice,
                        label: res.label,
                        error: null,
                      });
                    })
                    .catch((err: any) => {
                      setLatestAudio({
                        base64: null,
                        isCloned: false,
                        isMock: false,
                        fallback: false,
                        notice: null,
                        label: null,
                        error: err.message || "Failed to generate speech audio.",
                      });
                    })
                    .finally(() => setTtsLoading(false));
                }
              }}
            />
          )}

          {/* Latest question & answer (the newest answer replaces the previous one) */}
          <div style={{ flex: 1, marginTop: "1rem" }}>
            <h4 style={{ margin: "0 0 0.75rem", color: "#495057", fontSize: "0.95rem", borderBottom: "1px solid #dee2e6", paddingBottom: "0.5rem" }}>
              💬 Latest Answer
            </h4>

            {conversation.length === 0 ? (
              <div style={{ color: "#888", fontSize: "0.9rem", textAlign: "center", marginTop: "2rem" }}>
                No questions asked yet. Ask a question using the microphone above to start learning!
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                {conversation.map((msg) => (
                  <div
                    key={msg.id}
                    style={{
                      background: msg.role === "user" ? "#f1f3f5" : "#fff",
                      border: `1px solid ${msg.role === "user" ? "#dee2e6" : msg.grounded ? "#28a745" : "#ffc107"}`,
                      borderRadius: "8px",
                      padding: "1rem",
                    }}
                  >
                    {/* Header info */}
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem", fontSize: "0.85rem", color: "#666" }}>
                      <strong>{msg.role === "user" ? "🙋‍♂️ Student Voice Question" : "💡 AI Educational Tutor"}</strong>
                      <span>{msg.timestamp}</span>
                    </div>

                    {msg.role === "user" ? (
                      <p style={{ margin: 0, fontSize: "1rem", color: "#212529" }}>{msg.question}</p>
                    ) : (
                      <div>
                        {/* Grounded / Not-Grounded Banner */}
                        <div
                          style={{
                            padding: "0.4rem 0.75rem",
                            borderRadius: "4px",
                            fontSize: "0.85rem",
                            fontWeight: 600,
                            marginBottom: "0.75rem",
                            background: msg.grounded ? "#d4edda" : "#fff3cd",
                            color: msg.grounded ? "#155724" : "#856404",
                            border: `1px solid ${msg.grounded ? "#c3e6cb" : "#ffeeba"}`,
                          }}
                        >
                          {msg.grounded
                            ? `✅ Grounded in Study Material (${selectedChapter?.title}${msg.pageNumber ? ` • Page ${msg.pageNumber}` : ""})`
                            : "⚠️ Notice: This question isn't covered in the uploaded material."}
                        </div>

                        {/* Cloned Voice Label */}
                        {msg.isCloned && (
                          <div style={{ fontSize: "0.8rem", color: "#2e7d32", fontWeight: "bold", marginBottom: "0.5rem" }}>
                            🏷️ {msg.voiceLabel || "AI-generated voice, authorized by the teacher."}
                          </div>
                        )}

                        <p style={{ margin: "0 0 0.75rem", fontSize: "1rem", lineHeight: 1.6, whiteSpace: "pre-wrap", color: "#212529" }}>
                          {msg.answer}
                        </p>

                        {/* Citations & Sources */}
                        {msg.sources && msg.sources.length > 0 && (
                          <div style={{ marginTop: "0.75rem", borderTop: "1px solid #dee2e6", paddingTop: "0.5rem" }}>
                            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#6c757d", marginBottom: "0.25rem" }}>
                              📚 Sources Referenced:
                            </div>
                            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem", color: "#495057" }}>
                              {msg.sources.map((src: any, idx: number) => (
                                <li key={idx}>
                                  <strong>{src.document_name}</strong>
                                  {src.page_number ? ` (Page ${src.page_number})` : ""}: <em>"{src.excerpt}"</em>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Retrieval Debug (only returned when RAG_DEBUG is enabled) */}
                        {msg.debug && (
                          <details
                            data-testid="rag-debug"
                            style={{
                              marginTop: "0.75rem",
                              borderTop: "1px dashed #ced4da",
                              paddingTop: "0.5rem",
                              fontSize: "0.8rem",
                              color: "#6c757d",
                            }}
                          >
                            <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                              🐞 Debug (retrieval)
                            </summary>
                            <div style={{ marginTop: "0.5rem" }}>
                              <div>
                                Model: <code>{msg.debug.embedding_model}</code> • Query dim:{" "}
                                <code>{msg.debug.query_dimension}</code> • Threshold:{" "}
                                <code>{msg.debug.threshold}</code> • Candidates:{" "}
                                <code>{msg.debug.candidate_count}</code> • Dim mismatch:{" "}
                                <code>{msg.debug.dimension_mismatch_chunks}</code>
                              </div>
                              <ol style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                                {(msg.debug.scored_chunks || []).map((c: any) => (
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
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
