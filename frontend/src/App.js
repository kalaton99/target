import "@/App.css";
import "@/index.css";
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { AuthPage } from "@/pages/AuthPage";
import { MenuPage } from "@/pages/MenuPage";
import { TablesPage } from "@/pages/TablesPage";
import PlayPage from "@/pages/PlayPage";
import DicegetPage from "@/pages/DicegetPage";
import FlipgetPage from "@/pages/FlipgetPage";
import JackgetPage from "@/pages/JackgetPage";
import WalletPage from "@/pages/WalletPage";
import LobbyPage from "@/pages/LobbyPage";
import {
  GamesPage,
  PlatformHome,
  ProfilePlaceholder,
} from "@/pages/PlatformPages";
import {
  TmargetAdminMarketsPage,
  TmargetHomePage,
  TmargetMarketDetailPlaceholder,
  TmargetMarketsPage,
  TmargetPortfolioPage,
} from "@/pages/TmargetPages";

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
          <Route path="/" element={<PlatformHome />} />
          <Route path="/games" element={<GamesPage />} />
          <Route path="/target" element={<Navigate to="/lobby" replace />} />
          <Route path="/games/target" element={<Navigate to="/lobby" replace />} />
          <Route path="/games/diceget" element={<Navigate to="/diceget" replace />} />
          <Route path="/diceget" element={<DicegetPage />} />
          <Route path="/diceget/:tableId" element={<DicegetPage />} />
          <Route path="/games/flipget" element={<Navigate to="/flipget" replace />} />
          <Route path="/flipget" element={<FlipgetPage />} />
          <Route path="/flipget/:tableId" element={<FlipgetPage />} />
          <Route path="/games/jackget" element={<Navigate to="/jackget" replace />} />
          <Route path="/jackget" element={<JackgetPage />} />
          <Route path="/jackget/:tableId" element={<JackgetPage />} />
          <Route path="/tmarget" element={<TmargetHomePage />} />
          <Route path="/tmarget/markets" element={<TmargetMarketsPage />} />
          <Route path="/tmarget/markets/:slug" element={<TmargetMarketDetailPlaceholder />} />
          <Route path="/tmarget/portfolio" element={<TmargetPortfolioPage />} />
          <Route path="/tmarget/admin/markets" element={<TmargetAdminMarketsPage />} />
          <Route path="/wallet" element={<WalletPage />} />
          <Route path="/profile" element={<ProfilePlaceholder />} />
          <Route path="/lobby" element={<LobbyPage />} />
          <Route path="/play" element={<PlayPage />} />
          <Route path="/play/:tableId" element={<PlayPage />} />
          <Route path="/login" element={<PublicOnly><AuthPage mode="login" /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><AuthPage mode="register" /></PublicOnly>} />
          <Route path="/menu" element={<Protected><MenuPage /></Protected>} />
          <Route path="/tables" element={<Protected><TablesPage /></Protected>} />
          {/* 2026-05 v2 — legacy /table/:tableId GamePage removed along with
              backend/realtime/. The active gameplay surface is /play/:tableId
              powered by realtime_v2. */}
          <Route path="/table/:tableId" element={<Navigate to="/lobby" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
