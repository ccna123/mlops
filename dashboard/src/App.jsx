import { useState } from "react";
import AppShell from "./components/AppShell";
import Overview from "./pages/Overview";
import DataPage from "./pages/DataPage";
import Models from "./pages/Models";
import Drift from "./pages/Drift";
import { DemoModeProvider } from "./lib/DemoModeContext";
import { ToastProvider } from "./components/Toast";

/**
 * Renders the page matching the current nav selection.
 *
 * Args:
 *   page: Current page id ("overview" | "logs" | "data" | "models" | "drift").
 *   setPage: Setter to switch pages (used by Models' empty state and
 *     Drift's retrain call to action).
 *   prefillTaskType: task_type to pre-fill Overview's form with, or null.
 *   setPrefillTaskType: Setter, called with null once Overview consumes it.
 *
 * Returns:
 *   The JSX for the current page, or null for an unknown page id.
 */
function Router({ page, setPage, prefillTaskType, setPrefillTaskType }) {
  switch (page) {
    case "overview":
      return <Overview prefillTaskType={prefillTaskType} onConsumePrefill={() => setPrefillTaskType(null)} />;
    case "data":
      return <DataPage />;
    case "models":
      return <Models onNavigateToOverview={() => setPage("overview")} />;
    case "drift":
      return (
        <Drift
          onRetrain={(taskType) => {
            setPrefillTaskType(taskType);
            setPage("overview");
          }}
        />
      );
    default:
      return null;
  }
}

/**
 * Root component: five static pages behind AppShell, no router library
 * needed for this fixed set of screens (brief §4).
 *
 * Args:
 *   None.
 *
 * Returns:
 *   The app's JSX tree.
 */
export default function App() {
  const [page, setPage] = useState("overview");
  const [prefillTaskType, setPrefillTaskType] = useState(null);

  return (
    <DemoModeProvider>
      <ToastProvider>
        <AppShell page={page} onNavigate={setPage}>
          <Router page={page} setPage={setPage} prefillTaskType={prefillTaskType} setPrefillTaskType={setPrefillTaskType} />
        </AppShell>
      </ToastProvider>
    </DemoModeProvider>
  );
}
