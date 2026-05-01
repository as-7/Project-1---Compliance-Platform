import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Upload from "./pages/Upload";
import Controls from "./pages/Controls";
import Gaps from "./pages/Gaps";
import Chat from "./pages/Chat";

const tabs = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/upload", label: "Upload" },
  { to: "/controls", label: "Controls" },
  { to: "/gaps", label: "Gaps" },
  { to: "/chat", label: "Chat" },
];

export default function App() {
  return (
    <div className="min-h-full flex flex-col">
      <header className="bg-slate-900 text-white">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-6">
          <div className="font-semibold">Regulatory Compliance Intelligence</div>
          <nav className="flex gap-1 ml-6">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded text-sm transition ${
                    isActive
                      ? "bg-slate-700 text-white"
                      : "text-slate-300 hover:bg-slate-800 hover:text-white"
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/controls" element={<Controls />} />
          <Route path="/gaps" element={<Gaps />} />
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </main>
    </div>
  );
}
