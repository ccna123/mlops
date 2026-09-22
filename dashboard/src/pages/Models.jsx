import { useEffect, useState } from "react";
import { Crown, Trash2 } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import MetricTile from "../components/MetricTile";
import RelativeTime from "../components/RelativeTime";
import { formatNumber } from "../lib/format";
import { ApiError } from "../lib/api";

/**
 * Renders the Models screen: per-model metrics and champion promotion
 * (brief §4.4). Metric columns are derived from the response's own keys,
 * never hardcoded — the brief calls out a prior frontend bug that assumed
 * a fixed metric set.
 *
 * Args:
 *   onNavigateToOverview: Called when the empty state's link to Overview
 *     is clicked.
 *
 * Returns:
 *   A JSX page element.
 */
export default function Models({ onNavigateToOverview }) {
  const client = useClient();
  const pushToast = useToast();
  const [state, setState] = useState({ status: "loading" });
  const [promoteTarget, setPromoteTarget] = useState(null);
  const [promoting, setPromoting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteModelTarget, setDeleteModelTarget] = useState(null);

  async function load() {
    setState({ status: "loading" });
    try {
      const body = await client.listModels();
      setState({ status: "data", models: body.models });
    } catch (error) {
      setState({ status: "error", error });
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function confirmPromote() {
    if (!promoteTarget) return;
    setPromoting(true);
    try {
      await client.promote(promoteTarget.modelName, promoteTarget.toVersion);
      pushToast({ type: "success", text: `Đã chuyển champion của ${promoteTarget.modelName} sang v${promoteTarget.toVersion}` });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({ type: "error", text: `Không thể chuyển champion: ${typeof detail === "string" ? detail : "lỗi không xác định"}` });
    } finally {
      setPromoting(false);
      setPromoteTarget(null);
      load(); // always re-fetch real state, never assume the write worked (brief §4.4)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.deleteModelVersion(deleteTarget.modelName, deleteTarget.version);
      pushToast({ type: "success", text: `Đã xoá ${deleteTarget.modelName} v${deleteTarget.version}` });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({ type: "error", text: `Không xoá được: ${typeof detail === "string" ? detail : "lỗi không xác định"}` });
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
      load();
    }
  }

  async function confirmDeleteModel() {
    if (!deleteModelTarget) return;
    setDeleting(true);
    try {
      await client.deleteModel(deleteModelTarget.name);
      pushToast({ type: "success", text: `Đã xoá model ${deleteModelTarget.name}` });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({
        type: "error",
        text: `Không xoá được model: ${typeof detail === "string" ? detail : "lỗi không xác định"}`,
      });
    } finally {
      setDeleting(false);
      setDeleteModelTarget(null);
      load();
    }
  }

  return (
    <div className="page-grid-single">
      {state.status === "loading" && <LoadingSkeleton rows={6} />}
      {state.status === "error" && <ErrorState kind="system" detail={state.error.detail} onRetry={load} />}
      {state.status === "data" && state.models.length === 0 && (
        <EmptyState
          title="Chưa có model."
          description="Chạy pipeline để train model đầu tiên."
          action={
            <button className="btn-secondary" onClick={onNavigateToOverview}>
              Sang Tổng quan
            </button>
          }
        />
      )}
      {state.status === "data" &&
        state.models.map((model) => {
          const champion = model.versions.find((version) => version.is_champion);
          const metricKeys = [...new Set(model.versions.flatMap((version) => Object.keys(version.metrics)))];
          return (
            <section className="card card-wide" key={model.name}>
              <div className="section-head">
                <div>
                  <h2>{model.name}</h2>
                  <p className="section-sub">
                    {model.task_type}
                    {champion?.estimator && <> · {champion.estimator}</>}
                  </p>
                </div>
                <button
                  className="btn-danger-ghost"
                  disabled={promoting || deleting}
                  onClick={() => setDeleteModelTarget({ name: model.name, versionCount: model.versions.length })}
                >
                  <Trash2 size={14} /> Xoá model
                </button>
              </div>

              {champion && (
                <div className="metric-row">
                  {metricKeys
                    .filter((key) => key in champion.metrics)
                    .map((key) => (
                      <MetricTile key={key} name={key} value={champion.metrics[key]} />
                    ))}
                </div>
              )}

              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>VERSION</th>
                      <th>CHAMPION</th>
                      <th>THUẬT TOÁN</th>
                      {metricKeys.map((key) => (
                        <th key={key}>{key.toUpperCase()}</th>
                      ))}
                      <th>TẠO LÚC</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {model.versions.map((version) => (
                      <tr key={version.version}>
                        <td className="mono">v{version.version}</td>
                        <td>
                          {version.is_champion && (
                            <span className="champion-badge">
                              <Crown size={14} /> champion
                            </span>
                          )}
                        </td>
                        <td>{version.estimator ?? "—"}</td>
                        {metricKeys.map((key) => (
                          <td key={key}>{key in version.metrics ? formatNumber(version.metrics[key]) : "—"}</td>
                        ))}
                        <td>
                          <RelativeTime iso={version.created_at} />
                        </td>
                        <td>
                          {/* Champion row gets neither button: promoting it is a
                              no-op and deleting it is refused with a 409. */}
                          {!version.is_champion && (
                            <div className="row-actions">
                              <button
                                className="btn-secondary"
                                disabled={promoting || deleting}
                                onClick={() =>
                                  setPromoteTarget({
                                    modelName: model.name,
                                    fromVersion: champion?.version,
                                    toVersion: version.version,
                                  })
                                }
                              >
                                Đổi champion
                              </button>
                              <button
                                className="btn-danger-ghost"
                                disabled={promoting || deleting}
                                onClick={() => setDeleteTarget({ modelName: model.name, version: version.version })}
                                aria-label={`Xoá version ${version.version}`}
                              >
                                <Trash2 size={14} /> Xoá
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}

      {promoteTarget && (
        <ConfirmDialog
          title="Xác nhận đổi champion"
          confirmLabel="Đổi champion"
          busy={promoting}
          onConfirm={confirmPromote}
          onCancel={() => setPromoteTarget(null)}
        >
          <p>
            Chuyển champion của <b>{promoteTarget.modelName}</b> từ v{promoteTarget.fromVersion ?? "?"} sang v
            {promoteTarget.toVersion}.
          </p>
          <p className="warn-note">
            Alias đổi ngay trong Model Registry, nhưng dịch vụ serving chỉ nạp lại champion lúc khởi động hoặc khi
            được gọi <code>/reload</code>. Serving có thể vẫn trả lời bằng model cũ cho tới lúc đó.
          </p>
        </ConfirmDialog>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Xoá version này?"
          confirmLabel="Xoá vĩnh viễn"
          danger
          busy={deleting}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        >
          <p>
            Xoá <b>{deleteTarget.modelName}</b> version <b>v{deleteTarget.version}</b> khỏi Model Registry.
          </p>
          <p className="warn-note">
            Không hoàn tác được. Metric và lịch sử của version này biến mất khỏi Registry; các báo cáo drift đã tính
            trên nó vẫn còn trong object storage nhưng sẽ trỏ tới một version không còn tồn tại.
          </p>
        </ConfirmDialog>
      )}

      {deleteModelTarget && (
        <ConfirmDialog
          title="Xoá toàn bộ model này?"
          confirmLabel="Xoá toàn bộ model"
          danger
          busy={deleting}
          onConfirm={confirmDeleteModel}
          onCancel={() => setDeleteModelTarget(null)}
        >
          <p>
            Xoá <b>{deleteModelTarget.name}</b> khỏi Model Registry, kèm <b>tất cả {deleteModelTarget.versionCount}</b>{" "}
            version và alias champion.
          </p>
          <p className="warn-note">
            Không hoàn tác được. Sau khi xoá, <code>serving</code> vẫn trả lời bằng model đang nằm sẵn trong bộ nhớ
            cho tới lần khởi động lại hoặc <code>/reload</code> kế tiếp; từ đó trở đi <code>/predict</code> trả 503
            &ldquo;no champion loaded&rdquo; cho loại model này. Muốn có model trở lại thì phải chạy pipeline train
            và qua được cổng promote.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
