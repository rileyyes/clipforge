import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { applyTheme, getTheme, toggleTheme } from "./theme";
import { Icon, ToastProvider } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import Editor from "./pages/Editor";
import ExportPage from "./pages/ExportPage";
import AutoEditor from "./pages/AutoEditor";
import SettingsPage from "./pages/Settings";
import Thumbnails from "./pages/Thumbnails";
import Shorts from "./pages/Shorts";
import Publish from "./pages/Publish";

import { parseHash, type Route } from "./router";

function useRoute(): Route {
  const [r, setR] = useState(parseHash(window.location.hash));
  useEffect(() => {
    const f = () => setR(parseHash(window.location.hash));
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return r;
}

const NAV = [
  { page: "dashboard", label: "Dashboard", icon: "home" },
  { page: "auto", label: "AI Auto Editor", icon: "wand" },
  { page: "editor", label: "Manual Editor", icon: "film" },
  { page: "shorts", label: "Shorts", icon: "phone" },
  { page: "thumbs", label: "Thumbnails", icon: "image" },
  { page: "projects", label: "Projects", icon: "folder" },
  { page: "export", label: "Export", icon: "export" },
  { page: "publish", label: "Publish", icon: "upload" },
  { page: "settings", label: "Settings", icon: "gear" },
];

applyTheme(getTheme());

function ThemeButton({ wide }: { wide: boolean }) {
  const [t, setT] = useState(getTheme());
  useEffect(() => {
    const on = (e: Event) => setT((e as CustomEvent).detail);
    window.addEventListener("rjclip-theme", on);
    return () => window.removeEventListener("rjclip-theme", on);
  }, []);
  const next = t === "light" ? "dark" : "light";
  return (
    <button className="nav-item theme-btn" title={`Switch to the ${next} theme`} aria-label={`Switch to the ${next} theme`} onClick={toggleTheme}>
      <Icon name={t === "light" ? "moon" : "sun"} size={18} />{wide && (t === "light" ? "Dark theme" : "Light theme")}
    </button>
  );
}

function App() {
  const route = useRoute();
  const inEditor = route.page === "editor" && !!route.id;
  const lastProject = localStorage.getItem("cf:lastProject");
  return (
    <div className={"shell" + (inEditor ? " collapsed" : "")}>
      <nav className="sidebar" aria-label="Main">
        <div className="brand"><div className="brand-mark">▶</div>{!inEditor && "RJClip"}</div>
        {NAV.map((n) => {
          const target = (n.page === "editor" || n.page === "export" || n.page === "thumbs" || n.page === "publish") && lastProject ? `${n.page}/${lastProject}` : n.page;
          return (
            <a key={n.page} href={"#/" + target} title={n.label}
              className={"nav-item" + (route.page === n.page ? " active" : "")}>
              <Icon name={n.icon} size={18} />{!inEditor && n.label}
            </a>
          );
        })}
        <span style={{ flex: 1 }} />
        <ThemeButton wide={!inEditor} />
        {!inEditor && <div className="nav-foot">Local-first · v0.22</div>}
      </nav>
      <main className="main">
        {route.page === "dashboard" && <Dashboard />}
        {route.page === "projects" && <Projects />}
        {route.page === "editor" && (route.id ? <Editor key={route.id} projectId={route.id} /> : <Projects pickFor="editor" />)}
        {route.page === "export" && (route.id ? <ExportPage key={route.id} projectId={route.id} /> : <Projects pickFor="export" />)}
        {route.page === "auto" && <AutoEditor projectId={route.id || undefined} />}
        {route.page === "settings" && <SettingsPage />}
        {route.page === "thumbs" && <Thumbnails projectId={route.id || undefined} />}
        {route.page === "shorts" && <Shorts projectId={route.id || undefined} />}
        {route.page === "publish" && <Publish projectId={route.id || undefined} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<ToastProvider><App /></ToastProvider>);
