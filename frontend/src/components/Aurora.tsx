import React from "react";

/** Animated emerald aurora background + film grain. Pure CSS, cheap. */
export const Aurora: React.FC<{ dim?: boolean }> = ({ dim = false }) => (
  <>
    <div className={`aurora${dim ? " aurora-dim" : ""}`} aria-hidden="true">
      <div className="aurora-layer-3" />
    </div>
    <div className="grain" aria-hidden="true" />
  </>
);

/** Circle-and-dot logo mark (SVG in code). */
export const LogoMark: React.FC<{ size?: number }> = ({ size = 28 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    aria-hidden="true"
    style={{ flexShrink: 0 }}
  >
    <circle cx="16" cy="16" r="11" stroke="var(--color-accent)" strokeWidth="2.5" />
    <circle cx="16" cy="16" r="4" fill="var(--color-accent)" />
  </svg>
);
