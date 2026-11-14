import React from "react";

interface UserMenuProps {
  name?: string;
  role: "Teacher" | "Student";
  onLogout: () => void;
}

export const UserMenu: React.FC<UserMenuProps> = ({ name, role, onLogout }) => (
  <details className="user-menu">
    <summary aria-label={`Open ${role.toLowerCase()} menu`}>
      <span className="user-menu-name">{name || role}</span>
      <span className="user-menu-role">{role}</span>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="m4 6 4 4 4-4" />
      </svg>
    </summary>
    <div className="user-menu-panel">
      <span className="user-menu-label">Signed in as</span>
      <strong>{name || role}</strong>
      <button className="btn btn-secondary" onClick={onLogout}>Sign out</button>
    </div>
  </details>
);
