import { useState, useEffect } from "react";

function App() {
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((d) => setHealth(d.status))
      .catch(() => setHealth("unreachable"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", textAlign: "center", marginTop: "4rem" }}>
      <h1>🎓 ShikshaSaathi Voice</h1>
      <p>Multilingual AI-powered educational voice tutor</p>
      <p>
        Backend status: <strong>{health}</strong>
      </p>
    </main>
  );
}

export default App;
