import { useEffect, useRef, useState } from "react";
import { ChevronDown, HeartPulse, WifiOff } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { SERVICE_ORDER, SERVICE_LABELS } from "../lib/constants";

const POLL_INTERVAL_MS = 10000;

/**
 * Polls `GET /health` at most once every 10 seconds with at most one
 * in-flight request (brief §3.1 — overlapping health checks are a known
 * bug that can falsely report every service down), and renders the
 * five-service popover.
 *
 * Args:
 *   None. Reads the API client from DemoModeContext.
 *
 * Returns:
 *   A JSX health pill button with an expandable service popover.
 */
export default function HealthPill() {
  const client = useClient();
  const [health, setHealth] = useState(null);
  const [offline, setOffline] = useState(false);
  const [open, setOpen] = useState(false);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const body = await client.health();
        if (!cancelled) {
          setHealth(body);
          setOffline(false);
        }
      } catch {
        if (!cancelled) setOffline(true);
      } finally {
        inFlight.current = false;
      }
    }

    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [client]);

  let pillClass = "healthpill-loading";
  let label = "Đang kiểm tra…";
  if (offline) {
    pillClass = "healthpill-offline";
    label = "Không kết nối API";
  } else if (health) {
    pillClass = health.status === "ok" ? "healthpill-ok" : "healthpill-degraded";
    label = health.status === "ok" ? "Hệ thống ổn" : "Cần chú ý";
  }

  return (
    <div className="health-wrap">
      <button className={`healthpill ${pillClass}`} onClick={() => setOpen((prev) => !prev)}>
        {offline ? <WifiOff size={14} /> : <HeartPulse size={14} />}
        {label}
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="popover">
          <strong>Trạng thái dịch vụ</strong>
          {offline && <p className="popover-note">API không phản hồi. Không phân biệt được service nào hỏng.</p>}
          {!offline &&
            health &&
            SERVICE_ORDER.map((service) => (
              <div className="popover-row" key={service}>
                <span>
                  {SERVICE_LABELS[service]}
                  {service === "postgres" && <small> (suy ra qua Airflow)</small>}
                </span>
                <span className={`dot ${health.services[service] === "ok" ? "dot-ok" : "dot-down"}`}>
                  {health.services[service] ?? "—"}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
