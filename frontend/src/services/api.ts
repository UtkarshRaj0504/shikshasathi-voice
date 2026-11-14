/**
API client helper for backend communication.
*/

const TOKEN_KEY = "shiksha_token";

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

  const res = await fetch(`/api${endpoint}`, {
    ...options,
    headers,
  });

  if (res.status === 204) {
    return null;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed with status ${res.status}`);
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
};
