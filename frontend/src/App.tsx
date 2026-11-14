import { useState, useEffect } from "react";
import { getToken, api } from "./services/api";
import { Login } from "./components/Login";
import { TeacherDashboard } from "./components/TeacherDashboard";
import { StudentDashboard } from "./components/StudentDashboard";

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const checkAuth = async () => {
    const token = getToken();
    if (token) {
      try {
        const u = await api.getMe();
        setUser(u);
        setIsAuthenticated(true);
      } catch {
        setUser(null);
        setIsAuthenticated(false);
      } finally {
        setLoading(false);
      }
    } else {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  if (loading) {
    return <div style={{ textAlign: "center", marginTop: "4rem" }}>Loading ShikshaSaathi Voice...</div>;
  }

  if (!isAuthenticated) {
    return <Login onLoginSuccess={() => checkAuth()} />;
  }

  if (user?.role === "student") {
    return <StudentDashboard onLogout={() => { setIsAuthenticated(false); setUser(null); }} />;
  }

  return <TeacherDashboard onLogout={() => { setIsAuthenticated(false); setUser(null); }} />;
}

export default App;
