import React, { useEffect, useState } from "react";
import { api, removeToken } from "../services/api";

interface TeacherDashboardProps {
  onLogout: () => void;
}

export function TeacherDashboard({ onLogout }: TeacherDashboardProps) {
  const [user, setUser] = useState<any>(null);
  const [subjects, setSubjects] = useState<any[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<any>(null);
  const [chapters, setChapters] = useState<any[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<any>(null);
  const [documents, setDocuments] = useState<any[]>([]);

  // Form states
  const [newSubjectName, setNewSubjectName] = useState("");
  const [newSubjectDesc, setNewSubjectDesc] = useState("");
  const [newChapterTitle, setNewChapterTitle] = useState("");
  const [uploading, setUploading] = useState(false);
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

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedChapter) return;

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
      e.target.value = "";
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

  const getStatusBadge = (status: string) => {
    const styles: Record<string, { bg: string; color: string }> = {
      ready: { bg: "#d4edda", color: "#155724" },
      processing: { bg: "#fff3cd", color: "#856404" },
      pending: { bg: "#e2e3e5", color: "#383d41" },
      failed: { bg: "#f8d7da", color: "#721c24" },
    };
    const s = styles[status] || styles.pending;
    return (
      <span style={{ background: s.bg, color: s.color, padding: "0.2rem 0.5rem", borderRadius: "4px", fontSize: "0.85rem", fontWeight: "bold" }}>
        {status}
      </span>
    );
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "system-ui" }}>
      {/* Sidebar */}
      <aside style={{ width: "300px", background: "#f8f9fa", borderRight: "1px solid #dee2e6", padding: "1.5rem" }}>
        <h3>🎓 Teacher Dashboard</h3>
        {user && <p style={{ fontSize: "0.9rem", color: "#666", marginBottom: "1.5rem" }}>Logged in as: <strong>{user.name}</strong></p>}

        <button
          onClick={handleLogout}
          style={{ width: "100%", padding: "0.5rem", background: "#dc3545", color: "white", border: "none", borderRadius: "4px", marginBottom: "1.5rem", cursor: "pointer" }}
        >
          Sign Out
        </button>

        <h4>📚 Subjects</h4>
        <form onSubmit={handleCreateSubject} style={{ marginTop: "0.5rem", marginBottom: "1rem" }}>
          <input
            type="text"
            placeholder="Subject Name"
            value={newSubjectName}
            onChange={(e) => setNewSubjectName(e.target.value)}
            required
            style={{ width: "100%", padding: "0.4rem", marginBottom: "0.4rem", borderRadius: "4px", border: "1px solid #ccc" }}
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={newSubjectDesc}
            onChange={(e) => setNewSubjectDesc(e.target.value)}
            style={{ width: "100%", padding: "0.4rem", marginBottom: "0.4rem", borderRadius: "4px", border: "1px solid #ccc" }}
          />
          <button type="submit" style={{ width: "100%", padding: "0.4rem", background: "#28a745", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
            Add Subject
          </button>
        </form>

        <ul style={{ listStyle: "none", padding: 0 }}>
          {subjects.map((s) => (
            <li
              key={s.id}
              onClick={() => handleSelectSubject(s)}
              style={{
                padding: "0.75rem",
                background: selectedSubject?.id === s.id ? "#e9ecef" : "white",
                border: "1px solid #dee2e6",
                borderRadius: "4px",
                marginBottom: "0.5rem",
                cursor: "pointer",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>{s.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteSubject(s.id); }}
                style={{ background: "none", border: "none", color: "#dc3545", cursor: "pointer", fontSize: "0.9rem" }}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: "2rem" }}>
        {error && <div style={{ color: "red", background: "#f8d7da", padding: "0.75rem", borderRadius: "4px", marginBottom: "1rem" }}>{error}</div>}

        {!selectedSubject ? (
          <div style={{ textAlign: "center", marginTop: "4rem", color: "#666" }}>
            <h2>Select or create a subject from the sidebar to begin.</h2>
          </div>
        ) : (
          <div>
            <h2>📚 {selectedSubject.name}</h2>
            <p style={{ color: "#666", marginBottom: "2rem" }}>{selectedSubject.description || "No description provided."}</p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2rem" }}>
              {/* Chapters Column */}
              <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem" }}>
                <h3>📖 Chapters</h3>
                <form onSubmit={handleCreateChapter} style={{ margin: "1rem 0" }}>
                  <input
                    type="text"
                    placeholder="Chapter Title"
                    value={newChapterTitle}
                    onChange={(e) => setNewChapterTitle(e.target.value)}
                    required
                    style={{ width: "100%", padding: "0.5rem", marginBottom: "0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
                  />
                  <button type="submit" style={{ width: "100%", padding: "0.5rem", background: "#007bff", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
                    Add Chapter
                  </button>
                </form>

                <ul style={{ listStyle: "none", padding: 0 }}>
                  {chapters.map((c) => (
                    <li
                      key={c.id}
                      onClick={() => handleSelectChapter(c)}
                      style={{
                        padding: "0.75rem",
                        background: selectedChapter?.id === c.id ? "#e2e6ea" : "#f8f9fa",
                        border: "1px solid #ced4da",
                        borderRadius: "4px",
                        marginBottom: "0.5rem",
                        cursor: "pointer",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span>{c.order}. {c.title}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteChapter(c.id); }}
                        style={{ background: "none", border: "none", color: "#dc3545", cursor: "pointer" }}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Documents Column */}
              <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: "8px", padding: "1.5rem" }}>
                <h3>📄 Study Materials (PDF, DOCX, TXT)</h3>
                {!selectedChapter ? (
                  <p style={{ color: "#666", marginTop: "1rem" }}>Select a chapter to upload and view documents.</p>
                ) : (
                  <div>
                    <p style={{ fontWeight: "500", margin: "1rem 0 0.5rem" }}>Chapter: {selectedChapter.title}</p>
                    <div style={{ margin: "1rem 0" }}>
                      <label style={{ display: "block", padding: "1rem", border: "2px dashed #007bff", borderRadius: "8px", textAlign: "center", cursor: "pointer", background: "#f0f4f8" }}>
                        {uploading ? "Uploading & Processing..." : "📁 Click to Upload Document (Max 20MB)"}
                        <input type="file" accept=".pdf,.docx,.txt,.md" onChange={handleFileUpload} disabled={uploading} style={{ display: "none" }} />
                      </label>
                    </div>

                    <ul style={{ listStyle: "none", padding: 0 }}>
                      {documents.map((doc) => (
                        <li
                          key={doc.id}
                          style={{
                            padding: "0.75rem",
                            background: "#f8f9fa",
                            border: "1px solid #dee2e6",
                            borderRadius: "4px",
                            marginBottom: "0.5rem",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 500 }}>{doc.filename}</div>
                            <div style={{ marginTop: "0.25rem" }}>{getStatusBadge(doc.status)}</div>
                          </div>
                          <button
                            onClick={() => handleDeleteDocument(doc.id)}
                            style={{ background: "none", border: "none", color: "#dc3545", cursor: "pointer" }}
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
      </main>
    </div>
  );
}
