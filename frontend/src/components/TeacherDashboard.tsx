import React, { useEffect, useState } from "react";
import { api, removeToken } from "../services/api";
import { TeacherVoicePage } from "./TeacherVoicePage";
import { Aurora, LogoMark } from "./Aurora";
import { UserMenu } from "./UserMenu";

interface TeacherDashboardProps {
  onLogout: () => void;
}

export function TeacherDashboard({ onLogout }: TeacherDashboardProps) {
  const [view, setView] = useState<"materials" | "voice">("materials");
  const [user, setUser] = useState<any>(null);
  const [subjects, setSubjects] = useState<any[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<any>(null);
  const [chapters, setChapters] = useState<any[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<any>(null);
  const [documents, setDocuments] = useState<any[]>([]);

  const [newSubjectName, setNewSubjectName] = useState("");
  const [newSubjectDesc, setNewSubjectDesc] = useState("");
  const [newChapterTitle, setNewChapterTitle] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getMe()
      .then((u) => setUser(u))
      .catch(() => handleLogout());

    loadSubjects();
  }, []);

  const handleLogout = () => {
    removeToken();
    onLogout();
  };

  const loadSubjects = async () => {
    try {
      const data = await api.getSubjects();
      setSubjects(data);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCreateSubject = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createSubject(newSubjectName, newSubjectDesc);
      setNewSubjectName("");
      setNewSubjectDesc("");
      loadSubjects();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteSubject = async (id: number) => {
    if (!confirm("Delete this subject and all its chapters?")) return;
    try {
      await api.deleteSubject(id);
      if (selectedSubject?.id === id) {
        setSelectedSubject(null);
        setChapters([]);
        setSelectedChapter(null);
        setDocuments([]);
      }
      loadSubjects();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleSelectSubject = async (subject: any) => {
    setSelectedSubject(subject);
    setSelectedChapter(null);
    setDocuments([]);
    try {
      const chaps = await api.getChapters(subject.id);
      setChapters(chaps);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCreateChapter = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSubject) return;
    try {
      await api.createChapter(selectedSubject.id, newChapterTitle, chapters.length + 1);
      setNewChapterTitle("");
      const chaps = await api.getChapters(selectedSubject.id);
      setChapters(chaps);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteChapter = async (chapterId: number) => {
    if (!confirm("Delete this chapter and all its documents?")) return;
    try {
      await api.deleteChapter(chapterId);
      if (selectedChapter?.id === chapterId) {
        setSelectedChapter(null);
        setDocuments([]);
      }
      const chaps = await api.getChapters(selectedSubject.id);
      setChapters(chaps);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleSelectChapter = async (chapter: any) => {
    setSelectedChapter(chapter);
    try {
      const docs = await api.getDocuments(chapter.id);
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const uploadFile = async (file: File) => {
    if (!file || !selectedChapter || uploading) return;

    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(selectedChapter.id, file);
      const docs = await api.getDocuments(selectedChapter.id);
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void uploadFile(file);
    e.target.value = "";
  };

  const handleDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDropActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void uploadFile(file);
  };

  const handleDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDropActive(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLLabelElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
      setDropActive(false);
    }
  };

  const handleDeleteDocument = async (docId: number) => {
    if (!confirm("Delete this document?")) return;
    try {
      await api.deleteDocument(docId);
      const docs = await api.getDocuments(selectedChapter.id);
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleReprocessDocument = async (docId: number) => {
    if (!selectedChapter) return;
    setError(null);
    try {
      await api.reprocessDocument(docId);
      const docs = await api.getDocuments(selectedChapter.id);
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message);
    }
  };

  // Poll while any document is still being processed, so the status badge (and
  // any failure message) updates on its own. Stops as soon as nothing is
  // pending/processing.
  useEffect(() => {
    if (!selectedChapter) return;
    const inFlight = documents.some(
      (doc) => doc.status === "pending" || doc.status === "processing"
    );
    if (!inFlight) return;
    const timer = setInterval(() => {
      api
        .getDocuments(selectedChapter.id)
        .then((docs) => setDocuments(docs))
        .catch(() => {
          /* transient polling errors are ignored; the next tick retries */
        });
    }, 4000);
    return () => clearInterval(timer);
  }, [selectedChapter, documents]);

  const getStatusBadge = (status: string) => {
    const map: Record<string, string> = {
      ready: "badge-accent",
      processing: "badge-warning",
      pending: "badge-muted",
      failed: "badge-danger",
    };
    const cls = map[status] || "badge-muted";
    return <span className={`badge ${cls}`}>{status}</span>;
  };

  return (
    <div className="app-shell">
      <Aurora dim />
      <header className="app-header">
        <div className="header-left">
          <LogoMark size={24} />
          <div style={{ minWidth: 0 }}>
            <div className="app-title">Teacher Dashboard</div>
            {user && <div className="app-subtitle">Logged in as {user.name}</div>}
          </div>
        </div>
        <div className="header-right">
          <UserMenu name={user?.name} role="Teacher" onLogout={handleLogout} />
        </div>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <div className="nav-tabs">
            <button className={`nav-tab${view === "materials" ? " active" : ""}`} onClick={() => setView("materials")}>
              📚 Materials
            </button>
            <button className={`nav-tab${view === "voice" ? " active" : ""}`} onClick={() => setView("voice")}>
              🎙️ My Voice
            </button>
          </div>

          {view === "materials" && (
            <>
              <div className="sidebar-section">
                <h4>Subjects</h4>
                <form onSubmit={handleCreateSubject} style={{ marginTop: 8 }}>
                  <input
                    type="text"
                    placeholder="Subject Name"
                    value={newSubjectName}
                    onChange={(e) => setNewSubjectName(e.target.value)}
                    required
                    className="input"
                    style={{ marginBottom: 8 }}
                  />
                  <input
                    type="text"
                    placeholder="Description (optional)"
                    value={newSubjectDesc}
                    onChange={(e) => setNewSubjectDesc(e.target.value)}
                    className="input"
                    style={{ marginBottom: 8 }}
                  />
                  <button type="submit" className="btn btn-primary w-full" style={{ padding: "0.5rem" }}>
                    + Add Subject
                  </button>
                </form>
              </div>

              <div className="sidebar-section">
                <ul style={{ listStyle: "none", padding: 0 }}>
                  {subjects.map((s) => (
                    <li
                      key={s.id}
                      onClick={() => handleSelectSubject(s)}
                      className={`list-item${selectedSubject?.id === s.id ? " active" : ""}`}
                    >
                      <span className="item-name">{s.name}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteSubject(s.id); }}
                        className="btn-delete"
                        aria-label="Delete subject"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </aside>

        <main className="main-content">
          {view === "voice" ? (
            <TeacherVoicePage />
          ) : (
            <>
              {error && <div className="banner banner-danger" role="alert">{error}</div>}

              {!selectedSubject ? (
                <div style={{ textAlign: "center", marginTop: "4rem", color: "var(--color-text-muted)" }}>
                  <h2 style={{ marginBottom: 8 }}>Select or create a subject</h2>
                  <p>Add a subject from the sidebar to begin managing chapters and study materials.</p>
                </div>
              ) : (
                <div>
                  <h2 style={{ marginBottom: 4 }}>📚 {selectedSubject.name}</h2>
                  <p className="text-muted" style={{ marginBottom: 24 }}>{selectedSubject.description || "No description provided."}</p>

                  <div className="teacher-workspace">
                    {/* Chapters */}
                    <div className="card">
                      <h3 style={{ marginTop: 0 }}>📖 Chapters</h3>
                      <form onSubmit={handleCreateChapter} style={{ margin: "12px 0" }}>
                        <input
                          type="text"
                          placeholder="Chapter Title"
                          value={newChapterTitle}
                          onChange={(e) => setNewChapterTitle(e.target.value)}
                          required
                          className="input"
                          style={{ marginBottom: 8 }}
                        />
                        <button type="submit" className="btn btn-primary w-full" style={{ padding: "0.5rem" }}>
                          + Add Chapter
                        </button>
                      </form>

                      <ul style={{ listStyle: "none", padding: 0 }}>
                        {chapters.map((c) => (
                          <li
                            key={c.id}
                            onClick={() => handleSelectChapter(c)}
                            className={`list-item${selectedChapter?.id === c.id ? " active" : ""}`}
                          >
                            <span className="item-name">{c.order}. {c.title}</span>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDeleteChapter(c.id); }}
                              className="btn-delete"
                              aria-label="Delete chapter"
                            >
                              ✕
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Documents */}
                    <div className="card">
                      <h3 style={{ marginTop: 0 }}>📄 Study Materials</h3>
                      {!selectedChapter ? (
                        <p className="text-muted" style={{ marginTop: 12 }}>Select a chapter to upload and view documents.</p>
                      ) : (
                        <div>
                          <p className="text-muted" style={{ margin: "8px 0" }}>Chapter: {selectedChapter.title}</p>
                          <label
                            className={`dropzone${dropActive ? " drag-active" : ""}`}
                            style={{ marginTop: 8 }}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                            aria-busy={uploading}
                          >
                            {uploading ? (
                              <span>Uploading and processing…</span>
                            ) : (
                              <span>Drop a document here or click to browse (Max 20MB)</span>
                            )}
                            <input
                              type="file"
                              accept=".pdf,.docx,.txt,.md"
                              onChange={handleFileUpload}
                              disabled={uploading}
                              style={{ display: "none" }}
                            />
                          </label>

                          {uploading && (
                            <div className="upload-progress" role="progressbar" aria-label="Uploading document">
                              <div className="upload-progress-bar" />
                            </div>
                          )}

                          <ul style={{ listStyle: "none", padding: 0, marginTop: 12 }}>
                            {documents.map((doc) => (
                              <li key={doc.id} className="list-item">
                                <div style={{ minWidth: 0 }}>
                                  <div className="item-name">{doc.filename}</div>
                                  <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                                    {getStatusBadge(doc.status)}
                                    {doc.status === "failed" && (
                                      <button
                                        onClick={() => handleReprocessDocument(doc.id)}
                                        className="btn btn-secondary"
                                        style={{ padding: "0.15rem 0.6rem", fontSize: "0.75rem" }}
                                      >
                                        Retry
                                      </button>
                                    )}
                                  </div>
                                  {doc.status === "failed" && doc.error_message && (
                                    <div
                                      className="item-meta"
                                      style={{ color: "var(--color-danger)", marginTop: 4 }}
                                    >
                                      {doc.error_message}
                                    </div>
                                  )}
                                </div>
                                <button
                                  onClick={() => handleDeleteDocument(doc.id)}
                                  className="btn-delete"
                                >
                                  Delete
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
