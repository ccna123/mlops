import { LayoutDashboard, Database, Activity, FlaskConical, Brain, TrendingUpDownIcon } from "lucide-react";
import HealthPill from "./HealthPill";
import { useDemoMode } from "../lib/DemoModeContext";

const NAV_ITEMS = [
  { id: "overview", label: "Tổng quan", Icon: LayoutDashboard },
  { id: "data", label: "Dữ liệu", Icon: Database },
  { id: "models", label: "Models", Icon: Brain },
  { id: "drift", label: "Drift", Icon: TrendingUpDownIcon },
];

/**
 * Renders the four-item sidebar, topbar, and HealthPill shared by every
 * screen (brief §3.1), plus a demo-mode toggle for reviewing the UI with
 * the brief's captured JSON fixtures instead of a live API.
 *
 * Args:
 *   page: The current page id, one of NAV_ITEMS' ids.
 *   onNavigate: Callback invoked with the new page id when a nav item is
 *     clicked.
 *   children: The current page's content.
 *
 * Returns:
 *   A JSX layout element.
 */
export default function AppShell({ page, onNavigate, children }) {
  const { demo, setDemo } = useDemoMode();
  const current = NAV_ITEMS.find((item) => item.id === page);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Activity size={20} />
          <div>
            <div className="brand-title">MLOps</div>
            <div className="brand-sub">Control Room</div>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map(({ id, label, Icon }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? "nav-item-active" : ""}`}
              onClick={() => onNavigate(id)}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
        <button
          className={`demo-toggle ${demo ? "demo-toggle-on" : ""}`}
          onClick={() => setDemo((prev) => !prev)}
          title="Dùng dữ liệu mẫu từ brief thay vì gọi API thật"
        >
          <FlaskConical size={14} />
          Chế độ minh hoạ {demo ? "ON" : "OFF"}
        </button>
        <div className="sidebar-foot">Dự đoán giá nhà · pipeline operations</div>
      </aside>
      <div className="main-col">
        <header className="topbar">
          <div>
            <p className="eyebrow">MLOPS / {page}</p>
            <h1>{current?.label}</h1>
          </div>
          <HealthPill />
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
