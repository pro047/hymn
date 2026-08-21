import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { logout } from "./api/client";
import { fetchSession } from "./api/session";
import { Button } from "./components/ui/button";
import { isAuthenticated } from "./lib/auth-storage";
import AccountPage from "./pages/account-page";
import ChurchPage from "./pages/church-page";
import ForgotPasswordPage from "./pages/forgot-password-page";
import HomePage from "./pages/home-page";
import LoginPage from "./pages/login-page";
import ResetPasswordPage from "./pages/reset-password-page";
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

  // Handed to the page instead of layered over it. As a `fixed` sibling the
  // group stayed put while the header scrolled away, and it only cleared the
  // header's own right-hand side because the tab bar is hidden while
  // SAVED_SCORES_ENABLED is off — turning the flag on would have collided.
  return (
    <HomePage
      headerActions={
        <div className="flex flex-wrap items-center gap-2">
          {role === "leader" ? (
            <Button type="button" variant="outline" size="sm" asChild>
              <Link to="/church">교회 관리</Link>
            </Button>
          ) : null}
          {/* No role condition, unlike the link above: a member has a password
              too, which is why the change form is not on the church page. */}
          <Button type="button" variant="outline" size="sm" asChild>
            <Link to="/account">계정</Link>
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={logout}>
            로그아웃
          </Button>
        </div>
      }
    />
  );
}

function ProtectedChurchPage() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <ChurchPage />;
}

function ProtectedAccountPage() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <AccountPage />;
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
      {/* Unwrapped, unlike the two above. A signed-in user can still have
          forgotten their password — /account asks for the very password they
          cannot remember — and the reset link is opened wherever mail is read,
          which may be a browser that is already logged in. Bouncing either
          route to "/" would strand exactly the person they exist for. */}
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/church" element={<ProtectedChurchPage />} />
      <Route path="/account" element={<ProtectedAccountPage />} />
      <Route path="/" element={<ProtectedHomePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
