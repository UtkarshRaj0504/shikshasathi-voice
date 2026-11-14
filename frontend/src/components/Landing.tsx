import React, { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Aurora, LogoMark } from "./Aurora";

interface LandingProps {
  onStart: () => void;
  onForTeachers: () => void;
}

const TRACE_STEPS = [
  { label: "Listen", desc: "Voice → text" },
  { label: "Retrieve", desc: "Teacher's notes" },
  { label: "Understand", desc: "Ground the answer" },
  { label: "Answer", desc: "Translate if needed" },
  { label: "Speak", desc: "Authorized voice" },
];

const ArrowRight: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" className="arrow" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

function TracePanel() {
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (reduce) {
      setActive(TRACE_STEPS.length);
      return;
    }
    const timers: number[] = [];
    TRACE_STEPS.forEach((_, i) => {
      const t = window.setTimeout(() => setActive(i + 1), 400 + i * 520);
      timers.push(t);
    });
    return () => {
      timers.forEach(clearTimeout);
    };
  }, [reduce]);

  return (
    <div className="trace-panel" role="img" aria-label="Illustrative example of a single question run">
      <div className="trace-header">
        <span>
          Trace <span style={{ color: "var(--color-text-dim)" }}>/ Example run</span>
        </span>
        <span className="trace-example-tag">Illustrative example</span>
      </div>

      {TRACE_STEPS.map((step, i) => {
        const done = i < active;
        const current = i === active - 1;
        return (
          <div className="trace-row" key={step.label}>
            <span className="label">{step.label}</span>
            <div className="bar">
              <motion.div
                className="bar-fill"
                initial={{ scaleX: 0 }}
                animate={{ scaleX: done ? 1 : 0 }}
                transition={{ duration: 0.5, ease: "easeOut" }}
                style={{ transformOrigin: "left" }}
              />
              {current && !reduce && (
                <motion.div
                  className="scan-line"
                  initial={{ left: "0%", opacity: 0.8 }}
                  animate={{ left: "100%", opacity: 0 }}
                  transition={{ duration: 0.8, ease: "easeInOut" }}
                />
              )}
            </div>
          </div>
        );
      })}

      <div className="trace-footer">
        <span>
          <span className="dot" style={{ marginRight: 8 }} />
          Example run
        </span>
        <span>5 steps · 3 languages · Teacher-authorized voice</span>
      </div>
    </div>
  );
}

const STEPS = [
  {
    n: "01",
    title: "Teacher uploads notes & voice",
    desc: "Teachers add their study materials and record a short sample to create an authorized voice, with explicit consent.",
  },
  {
    n: "02",
    title: "Student reads the PDF",
    desc: "Students open the chapter and read the teacher's uploaded notes in a built-in PDF reader.",
  },
  {
    n: "03",
    title: "Ask by voice",
    desc: "Students press record and ask a question in English, Hindi, Kannada and other supported languages.",
  },
  {
    n: "04",
    title: "Hear the answer",
    desc: "Answers are grounded in the teacher's notes and spoken aloud in the teacher's authorized AI voice.",
  },
];

const FEATURES = [
  {
    title: "Grounded answers",
    desc: "Every answer is checked against the teacher's uploaded notes. Out-of-scope questions are refused, not invented.",
  },
  {
    title: "Voice questions",
    desc: "Ask by speaking — no typing required. Transcription runs automatically and can be edited before sending.",
  },
  {
    title: "English · Hindi · Kannada",
    desc: "Ask and answer in multiple Indian languages. Non-English questions are matched against English notes and translated back.",
  },
  {
    title: "Authorized teacher voices",
    desc: "Cloned voices are only created after the teacher confirms consent, and can be revoked or deleted at any time.",
  },
  {
    title: "Labelled AI voice",
    desc: "AI-generated speech is always clearly labelled so students know when they are hearing a synthetic voice.",
  },
  {
    title: "Chapter-by-chapter questions",
    desc: "Ask multiple questions about the selected chapter. Each new question replaces the previous answer and is grounded in the notes.",
  },
];

export const Landing: React.FC<LandingProps> = ({ onStart, onForTeachers }) => {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const fadeUp = {
    hidden: { opacity: 0, y: 16 },
    show: { opacity: 1, y: 0 },
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      <Aurora />

      {/* Navbar */}
      <nav
        className="navbar"
        style={{
          background: scrolled ? "rgba(5,15,13,0.85)" : "transparent",
          borderBottom: scrolled ? "1px solid var(--color-border)" : "1px solid transparent",
        }}
      >
        <a href="#top" className="navbar-brand">
          <LogoMark />
          <span>ShikshaSaathi</span>
        </a>
        <ul className="navbar-links">
          <li><a href="#product">Product</a></li>
          <li><a href="#how">How it works</a></li>
          <li><a href="#languages">Languages</a></li>
          <li><a href="#teachers">Teachers</a></li>
        </ul>
        <div className="navbar-actions">
          <button className="btn btn-primary" onClick={onStart}>
            Get Started <ArrowRight />
          </button>
        </div>
      </nav>

      {/* Hero */}
      <header className="hero" id="top">
        <motion.div
          variants={fadeUp}
          initial="hidden"
          animate="show"
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="hero-eyebrow">Voice-first learning</span>
          <h1>
            Ask in your language.
            <br />
            <span className="line-2">Hear your teacher.</span>
          </h1>
          <p className="hero-sub">
            Students ask by voice and get explanations from their teacher's own uploaded notes —
            spoken in the teacher's authorized AI voice, grounded in the material.
          </p>
          <div className="hero-actions">
            <button className="btn btn-primary" onClick={onStart}>
              Start learning <ArrowRight />
            </button>
            <button className="btn btn-secondary" onClick={onForTeachers}>
              For teachers <ArrowRight />
            </button>
          </div>
        </motion.div>

        <motion.div
          variants={fadeUp}
          initial="hidden"
          animate="show"
          transition={{ duration: 0.7, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
        >
          <TracePanel />
        </motion.div>
      </header>

      {/* How it works */}
      <section className="section" id="how" style={{ maxWidth: 1240, margin: "0 auto", padding: "0 24px" }}>
        <motion.h2
          variants={fadeUp}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          style={{ fontSize: "clamp(1.6rem, 3.5vw, 2.4rem)", marginBottom: 8 }}
        >
          How it works
        </motion.h2>
        <p className="text-muted" style={{ maxWidth: 520 }}>
          A short path from a teacher's notes to a student hearing the answer in the teacher's voice.
        </p>
        <div className="steps-grid">
          {STEPS.map((s, i) => (
            <motion.div
              key={s.n}
              className="step"
              variants={fadeUp}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.06 }}
            >
              <div className="step-num">STEP {s.n}</div>
              <div className="step-title">{s.title}</div>
              <div className="step-desc">{s.desc}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="section" id="product" style={{ maxWidth: 1240, margin: "0 auto", padding: "0 24px" }}>
        <motion.h2
          variants={fadeUp}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          style={{ fontSize: "clamp(1.6rem, 3.5vw, 2.4rem)", marginBottom: 8 }}
        >
          Built for honest, grounded learning
        </motion.h2>
        <p className="text-muted" style={{ maxWidth: 560 }}>
          Every feature below is something the app does today.
        </p>
        <div className="features-grid">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              className="feature"
              variants={fadeUp}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.4, delay: i * 0.05 }}
            >
              <div className="feature-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter">
                  <path d="M9 11l3 3L22 4" />
                  <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                </svg>
              </div>
              <div className="feature-title">{f.title}</div>
              <div className="feature-desc">{f.desc}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Languages */}
      <section className="section" id="languages" style={{ maxWidth: 1240, margin: "0 auto", padding: "0 24px" }}>
        <motion.h2
          variants={fadeUp}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          style={{ fontSize: "clamp(1.6rem, 3.5vw, 2.4rem)", marginBottom: 8 }}
        >
          Speak your language
        </motion.h2>
        <p className="text-muted" style={{ maxWidth: 560 }}>
          Questions and answers work across English, Hindi, Kannada, Tamil, Telugu, Marathi,
          Gujarati, Bengali, Malayalam, Punjabi and Assamese. Non-English questions are matched
          against English notes and answered in the language the student chooses.
        </p>
      </section>

      {/* Teachers */}
      <section className="section" id="teachers" style={{ maxWidth: 1240, margin: "0 auto", padding: "0 24px" }}>
        <div className="card" style={{ padding: "40px" }}>
          <h3 style={{ fontSize: "clamp(1.4rem, 3vw, 2rem)", marginBottom: 12 }}>For teachers</h3>
          <p className="text-muted" style={{ maxWidth: 600, marginBottom: 16 }}>
            Upload your notes, create an authorized voice clone with your explicit consent, and your
            students can hear study answers narrated in your voice. You can revoke or delete a voice
            at any time — students then fall back to the default educational voice.
          </p>
          <div className="banner banner-info" style={{ marginTop: 16, maxWidth: 680 }}>
            <span>
              <strong>Consent & transparency:</strong> AI-generated voice is always labelled to
              students. Cloning only happens after you confirm the consent statement, and you can
              revoke or delete your voices at any time.
            </span>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{ maxWidth: 1240, margin: "0 auto" }}>
        <div className="cta-block">
          <h2>Ready to learn by voice?</h2>
          <p>Sign in to start reading your teacher's notes and asking questions out loud.</p>
          <button className="btn btn-primary" onClick={onStart}>
            Get Started <ArrowRight />
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="footer">
        <div className="footer-inner">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LogoMark size={20} />
            <span style={{ fontWeight: 700, color: "var(--color-text)" }}>ShikshaSaathi Voice</span>
          </div>
          <span>Voice-first learning, grounded in your teacher's notes.</span>
          <span>© {new Date().getFullYear()} ShikshaSaathi</span>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
