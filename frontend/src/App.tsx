import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import { getToken, removeToken, api } from "./services/api";
import { Login } from "./components/Login";
import { TeacherDashboard } from "./components/TeacherDashboard";
import { StudentDashboard } from "./components/StudentDashboard";
import { Landing } from "./components/Landing";

function LandingPage() {
  const navigate = useNavigate();
  return (
    <Landing
      onStart={() => navigate("/login")}
      onForTeachers={() => navigate("/login")}
    />
  );
}

function LoginPage() {
  const navigate = useNavigate();
  return <Login onLoginSuccess={() => navigate("/app", { replace: true })} />;
}

function AppPage() {
  const navigate = useNavigate();
  const location = useLocation();
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
  }, [location.pathname]);

  if (loading) {
    return (
      <div className="app-shell" role="status" aria-label="Loading ShikshaSaathi">
        <div className="auth-wrap">
          <div className="auth-card loading-card" aria-hidden="true">
            <div className="skeleton loading-mark" />
            <div className="skeleton loading-heading" />
            <div className="skeleton loading-line" />
            <div className="skeleton loading-line loading-line-short" />
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const logout = () => {
    removeToken();
    setIsAuthenticated(false);
    setUser(null);
    navigate("/", { replace: true });
  };

  if (user?.role === "student") {
    return <StudentDashboard onLogout={logout} />;
  }

  return <TeacherDashboard onLogout={logout} />;
}

function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/app" element={<AppPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  );
}

export default App;
