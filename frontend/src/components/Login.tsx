import React, { useState } from "react";
import { api, setToken } from "../services/api";

interface LoginProps {
  onLoginSuccess: () => void;
}

export function Login({ onLoginSuccess }: LoginProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("teacher");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isRegister) {
        await api.register(email, name, password, role);
        // Auto login after registration
        const tokenRes = await api.login(email, password);
        setToken(tokenRes.access_token);
      } else {
        const tokenRes = await api.login(email, password);
        setToken(tokenRes.access_token);
      }
      onLoginSuccess();
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "400px", margin: "4rem auto", padding: "2rem", border: "1px solid #ddd", borderRadius: "8px", boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}>
      <h2>🎓 ShikshaSaathi Voice</h2>
      <p style={{ color: "#666", marginBottom: "1.5rem" }}>{isRegister ? "Create your account" : "Sign in to your account"}</p>

      {error && <div style={{ color: "red", background: "#f8d7da", padding: "0.75rem", borderRadius: "4px", marginBottom: "1rem" }}>{error}</div>}

      <form onSubmit={handleSubmit}>
        {isRegister && (
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>Full Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
            />
          </div>
        )}

        <div style={{ marginBottom: "1rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>Email Address</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
          />
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
          />
        </div>

        {isRegister && (
          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              style={{ width: "100%", padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
            >
              <option value="teacher">Teacher</option>
              <option value="student">Student</option>
            </select>
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{ width: "100%", padding: "0.75rem", background: "#007bff", color: "white", border: "none", borderRadius: "4px", fontWeight: "bold", cursor: "pointer" }}
        >
          {loading ? "Processing..." : isRegister ? "Register" : "Sign In"}
        </button>
      </form>

      <div style={{ marginTop: "1.5rem", textAlign: "center" }}>
        <button
          onClick={() => setIsRegister(!isRegister)}
          style={{ background: "none", border: "none", color: "#007bff", cursor: "pointer", textDecoration: "underline" }}
        >
          {isRegister ? "Already have an account? Sign in" : "Need an account? Register"}
        </button>
      </div>
    </div>
  );
}
