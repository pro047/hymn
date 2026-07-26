import { Navigate, Route, Routes } from "react-router-dom";

import { logout } from "./api/client";
import { Button } from "./components/ui/button";
import { isAuthenticated } from "./lib/auth-storage";
import HomePage from "./pages/home-page";
import LoginPage from "./pages/login-page";
import SignupPage from "./pages/signup-page";

function ProtectedHomePage() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="relative">
      <div className="fixed right-4 top-4 z-20">
        <Button type="button" variant="outline" size="sm" onClick={logout}>
          로그아웃
        </Button>
      </div>
      <HomePage />
    </div>
  );
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
      <Route path="/" element={<ProtectedHomePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
