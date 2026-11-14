import { useState, useEffect } from "react";
import { getToken, api } from "./services/api";
import { Login } from "./components/Login";
import { TeacherDashboard } from "./components/TeacherDashboard";

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    const token = getToken();
    if (token) {
      api.getMe()
        .then(() => setIsAuthenticated(true))
        .catch(() => setIsAuthenticated(false))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  if (loading) {
    return <div style={{ textAlign: "center", marginTop: "4rem" }}>Loading ShikshaSaathi Voice...</div>;
  }

  if (!isAuthenticated) {
    return <Login onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return <TeacherDashboard onLogout={() => setIsAuthenticated(false)} />;
}

export default App;
