import "@/App.css";
import "@/index.css";
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { AuthPage } from "@/pages/AuthPage";
import { MenuPage } from "@/pages/MenuPage";
import { TablesPage } from "@/pages/TablesPage";
import { GamePage } from "@/pages/GamePage";
import PlayPage from "@/pages/PlayPage";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center font-luxe text-gold tracking-widest">LOADING...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/menu" replace />;
  return children;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/play" replace />} />
          <Route path="/play" element={<PlayPage />} />
          <Route path="/login" element={<PublicOnly><AuthPage mode="login" /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><AuthPage mode="register" /></PublicOnly>} />
          <Route path="/menu" element={<Protected><MenuPage /></Protected>} />
          <Route path="/tables" element={<Protected><TablesPage /></Protected>} />
          <Route path="/table/:tableId" element={<Protected><GamePage /></Protected>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
