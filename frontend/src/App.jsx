import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { logout } from "./api/client";
import { fetchSession } from "./api/session";
import { Button } from "./components/ui/button";
import { isAuthenticated } from "./lib/auth-storage";
import AccountPage from "./pages/account-page";
import ChurchPage from "./pages/church-page";
import ContiPage from "./pages/conti-page";
import ForgotPasswordPage from "./pages/forgot-password-page";
import HomePage from "./pages/home-page";
import LoginPage from "./pages/login-page";
import ResetPasswordPage from "./pages/reset-password-page";
import SignupPage from "./pages/signup-page";

// "pending" until /auth/me answers, then "leader" or "member" — or null when
// the answer could not be read. Both screens below decide on the same four
// states, so the role is read in one place.
function useSessionRole(authenticated) {
  const [role, setRole] = useState("pending");

  useEffect(() => {
    // Guarded: without a token apiFetch would take the 401 path, fail to
    // refresh, and hard-navigate to /login — replacing the router's own
    // redirect with a full page load.
    if (!authenticated) return undefined;

    let active = true;
    fetchSession().then((session) => {
      if (active) setRole(session?.role ?? null);
    });
    return () => {
      active = false;
    };
  }, [authenticated]);

  return role;
}

function ProtectedHomePage() {
  const authenticated = isAuthenticated();
  const role = useSessionRole(authenticated);

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  // Held back while pending and for a known member; shown to a leader and
  // also when the session could not be read. That last case is a leader on a
  // bad connection far more often than anything else, and taking every way to
  // manage the week off their screen without a word is worse than offering a
  // member controls the server will refuse anyway.
  const canManage = role !== "pending" && role !== "member";

  // Handed to the page instead of layered over it. As a `fixed` sibling the
  // group stayed put while the header scrolled away and collided with the tab
  // bar that now shares the header.
  return (
    <HomePage
      canManage={canManage}
      headerActions={
        <div className="flex flex-wrap items-center gap-2">
          {/* A known leader only, unlike canManage: the link leads to a screen
              that itself says "리더만 확인할 수 있습니다" to anyone else. */}
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

function ProtectedContiPage() {
  // The conti screen is the leader's alone. While the role is pending it is
  // held back rather than drawn and withdrawn: mounting it sends the GET the
  // server refuses a member, and the member would see that refusal.
  const authenticated = isAuthenticated();
  const role = useSessionRole(authenticated);

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }
  if (role === "pending") {
    return null;
  }
  // Only a known member is turned away. An unreadable session (null) falls
  // through to the screen, where the server still decides and its own error
  // is shown — a leader on a bad connection must not be bounced home.
  if (role === "member") {
    return <Navigate to="/" replace />;
  }
  return <ContiPage />;
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
      <Route path="/conti/:week" element={<ProtectedContiPage />} />
      <Route path="/" element={<ProtectedHomePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
