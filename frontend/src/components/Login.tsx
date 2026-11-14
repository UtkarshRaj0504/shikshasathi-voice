import React, { useState } from "react";
import { api, setToken } from "../services/api";
import { Aurora, LogoMark } from "./Aurora";

interface LoginProps {
  onLoginSuccess: () => void;
}

const ArrowRight: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" className="arrow" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

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
    <div className="auth-wrap">
      <Aurora />
      <div className="auth-card">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
          <LogoMark size={28} />
          <span style={{ fontWeight: 800, fontSize: "1.1rem", letterSpacing: "-0.02em" }}>ShikshaSaathi</span>
        </div>

        <h1>{isRegister ? "Create your account" : "Sign in"}</h1>
        <p className="auth-sub">{isRegister ? "Sign up to upload notes and an authorized voice, or to start learning." : "Sign in to your account."}</p>

        {error && (
          <div className="banner banner-danger" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {isRegister && (
            <div className="field">
              <label className="field-label" htmlFor="name">Full Name</label>
              <input
                id="name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="input"
                autoComplete="name"
              />
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor="email">Email Address</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input"
              autoComplete="email"
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="input"
              autoComplete={isRegister ? "new-password" : "current-password"}
            />
          </div>

          {isRegister && (
            <div className="field">
              <label className="field-label">I am a</label>
              <div className="role-picker">
                <button
                  type="button"
                  className={`role-option${role === "teacher" ? " active" : ""}`}
                  aria-pressed={role === "teacher"}
                  onClick={() => setRole("teacher")}
                >
                  Teacher
                </button>
                <button
                  type="button"
                  className={`role-option${role === "student" ? " active" : ""}`}
                  aria-pressed={role === "student"}
                  onClick={() => setRole("student")}
                >
                  Student
                </button>
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary w-full"
          >
            {loading ? "Processing..." : isRegister ? "Register" : "Sign In"} <ArrowRight />
          </button>
        </form>

        <div className="auth-link">
          {isRegister ? "Already have an account? " : "Need an account? "}
          <button type="button" onClick={() => { setIsRegister(!isRegister); setError(null); }}>
            {isRegister ? "Sign in" : "Register"}
          </button>
        </div>
      </div>
    </div>
  );
}
