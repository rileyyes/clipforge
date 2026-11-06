import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
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

function App() {
  const route = useRoute();
  const inEditor = route.page === "editor" && !!route.id;
  const lastProject = localStorage.getItem("cf:lastProject");
  return (
    <div className={"shell" + (inEditor ? " collapsed" : "")}>
      <nav className="sidebar" aria-label="Main">
        <div className="brand"><div className="brand-mark">▶</div>{!inEditor && "ClipForge"}</div>
        {NAV.map((n) => {
          const target = (n.page === "editor" || n.page === "export" || n.page === "thumbs" || n.page === "publish") && lastProject ? `${n.page}/${lastProject}` : n.page;
          return (
            <a key={n.page} href={"#/" + target} title={n.label}
              className={"nav-item" + (route.page === n.page ? " active" : "")}>
              <Icon name={n.icon} size={18} />{!inEditor && n.label}
            </a>
          );
        })}
        {!inEditor && <div className="nav-foot">Local-first · v0.12</div>}
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
