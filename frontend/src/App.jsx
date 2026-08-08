import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { logout } from "./api/client";
import { fetchSession } from "./api/session";
import { Button } from "./components/ui/button";
import { isAuthenticated } from "./lib/auth-storage";
import ChurchPage from "./pages/church-page";
import HomePage from "./pages/home-page";
import LoginPage from "./pages/login-page";
import SignupPage from "./pages/signup-page";

function ProtectedHomePage() {
  // Null until /auth/me answers, and again if it never does. The management
  // link is offered only to a leader, so an unknown role shows nothing rather
  // than a link that would only lead to "리더만 확인할 수 있습니다".
  const [role, setRole] = useState(null);
  const authenticated = isAuthenticated();

  useEffect(() => {
    // Guarded: without a token apiFetch would take the 401 path, fail to
    // refresh, and hard-navigate to /login — replacing the router's own
    // redirect below with a full page load.
    if (!authenticated) return undefined;

    let active = true;
    fetchSession().then((session) => {
      if (active) setRole(session?.role ?? null);
    });
    return () => {
      active = false;
    };
  }, [authenticated]);

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="relative">
      <div className="fixed right-4 top-4 z-20 flex gap-2">
        {role === "leader" ? (
          <Button type="button" variant="outline" size="sm" asChild>
            <Link to="/church">교회 관리</Link>
          </Button>
        ) : null}
        <Button type="button" variant="outline" size="sm" onClick={logout}>
          로그아웃
        </Button>
      </div>
      <HomePage />
    </div>
  );
}

function ProtectedChurchPage() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <ChurchPage />;
}

function LoginRoute() {
  if (isAuthenticated()) {
    return <Navigate to="/" replace />;
  }
  return <LoginPage />;
}

function SignupRoute() {
  if (isAuthenticated()) {
    return <Navigate to="/" replace />;
  }
  return <SignupPage />;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/signup" element={<SignupRoute />} />
      <Route path="/church" element={<ProtectedChurchPage />} />
      <Route path="/" element={<ProtectedHomePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
