/**
API client helper for backend communication.
*/

const TOKEN_KEY = "shiksha_token";
const API_BASE_URL = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");

export class BackendUnavailableError extends Error {
  constructor(message = "The backend is unreachable or is still waking up. Please wait a moment and try again.") {
    super(message);
    this.name = "BackendUnavailableError";
  }
}

function apiUrl(endpoint: string): string {
  return `${API_BASE_URL}${endpoint}`;
}

function ensureApiConfigured(): void {
  if (!API_BASE_URL) {
    throw new BackendUnavailableError(
      "The backend URL is not configured. Set VITE_API_URL in the frontend environment and rebuild or redeploy."
    );
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request(endpoint: string, options: RequestInit = {}) {
  ensureApiConfigured();
  const token = getToken();
  const headers: HeadersInit = {
    ...(options.headers || {}),
  };

  if (!(options.body instanceof FormData)) {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(apiUrl(endpoint), { ...options, headers });
  } catch {
    throw new BackendUnavailableError();
  }

  if ([502, 503, 504].includes(res.status)) {
    throw new BackendUnavailableError(
      "The backend is starting or temporarily unavailable. Please wait a moment and retry."
    );
  }

  if (res.status === 204) {
    return null;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    let message: string;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object" && detail.message) {
      message = detail.code ? `${detail.code}: ${detail.message}` : detail.message;
    } else if (Array.isArray(detail)) {
      message = detail.map((item: any) => item.msg || JSON.stringify(item)).join("; ");
    } else {
      message = `Request failed with status ${res.status}`;
    }
    throw new Error(message);
  }
  return data;
}

export const api = {
  login: (email: string, password: string) =>
    request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  register: (email: string, name: string, password: string, role: string) =>
    request("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, name, password, role }),
    }),

  getMe: () => request("/auth/me"),

  getSubjects: () => request("/subjects"),

  createSubject: (name: string, description?: string) =>
    request("/subjects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  deleteSubject: (id: number) =>
    request(`/subjects/${id}`, { method: "DELETE" }),

  getChapters: (subjectId: number) =>
    request(`/subjects/${subjectId}/chapters`),

  createChapter: (subjectId: number, title: string, order = 0) =>
    request(`/subjects/${subjectId}/chapters`, {
      method: "POST",
      body: JSON.stringify({ title, order }),
    }),

  deleteChapter: (chapterId: number) =>
    request(`/subjects/chapters/${chapterId}`, { method: "DELETE" }),

  getDocuments: (chapterId: number) =>
    request(`/chapters/${chapterId}/documents`),

  uploadDocument: (chapterId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request(`/chapters/${chapterId}/documents/upload`, {
      method: "POST",
      body: formData,
    });
  },

  deleteDocument: (documentId: number) =>
    request(`/documents/${documentId}`, { method: "DELETE" }),

  fetchDocumentFile: async (documentId: number): Promise<ArrayBuffer> => {
    ensureApiConfigured();
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    let res: Response;
    try {
      res = await fetch(apiUrl(`/documents/${documentId}/file`), { headers });
    } catch {
      throw new BackendUnavailableError();
    }
    if ([502, 503, 504].includes(res.status)) {
      throw new BackendUnavailableError(
        "The backend is starting or temporarily unavailable. Please wait a moment and retry."
      );
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Failed to fetch file (${res.status})`);
    }
    return res.arrayBuffer();
  },

  getPreferences: () => request("/me/preferences"),

  updatePreferences: (data: {
    voice_profile_id: number | null;
    question_language?: string;
    answer_language?: string;
  }) =>
    request("/me/preferences", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  getVoices: () => request("/voices"),

  // ---- Teacher voice cloning (teacher only) ----
  getVoiceConsent: () => request("/voice-profiles/consent"),

  getVoiceProfiles: () => request("/voice-profiles"),

  createVoiceProfile: (
    file: File | Blob,
    voiceName: string,
    consentConfirmed: boolean,
    languages?: string,
    filename = "sample.wav"
  ) => {
    const formData = new FormData();
    formData.append("file", file, filename);
    formData.append("voice_name", voiceName);
    formData.append("consent_confirmed", consentConfirmed ? "true" : "false");
    if (languages) formData.append("languages", languages);
    return request("/voice-profiles", { method: "POST", body: formData });
  },

  previewVoiceProfile: (id: number) =>
    request(`/voice-profiles/${id}/preview`, { method: "POST" }),

  deleteVoiceProfile: (id: number) =>
    request(`/voice-profiles/${id}`, { method: "DELETE" }),

  revokeVoiceProfile: (id: number) =>
    request(`/voice-profiles/${id}/revoke`, { method: "POST" }),

  speakText: (text: string, voiceProfileId: number | null, language: string = "en") =>
    request("/tts/speak", {
      method: "POST",
      body: JSON.stringify({
        text,
        voice_profile_id: voiceProfileId,
        language,
      }),
    }),

  transcribeAudio: (audioBlob: Blob, languageCode: string = "indic-auto") => {
    const formData = new FormData();
    const mime = audioBlob.type || "";
    let filename = "audio.wav";
    if (mime.includes("webm")) {
      filename = "audio.webm";
    } else if (mime.includes("mp4") || mime.includes("m4a")) {
      filename = "audio.m4a";
    } else if (mime.includes("mp3") || mime.includes("mpeg")) {
      filename = "audio.mp3";
    } else if (mime.includes("ogg")) {
      filename = "audio.ogg";
    }

    formData.append("audio", audioBlob, filename);
    formData.append("language_code", languageCode);
    return request("/stt/transcribe", {
      method: "POST",
      body: formData,
    });
  },

  askQuestion: (
    question: string,
    chapterId?: number,
    answerLanguage: string = "en",
    level: string = "intermediate",
    currentPage?: number
  ) =>
    request("/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        chapter_id: chapterId,
        answer_language: answerLanguage,
        level,
        current_page: currentPage,
      }),
    }),
};
