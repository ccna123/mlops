import { useState } from "react";
import { Copy, ExternalLink, FileBarChart } from "lucide-react";

/**
 * Shows Evidently's own HTML report for one monitoring run.
 *
 * What it adds over the strips above: Evidently's own view of every section
 * of this run — which feature drifted and how, a summary of each column, the
 * prediction distribution and the performance plots (residuals, or confusion
 * matrix and ROC), served records drawn over the test set. Input quality is
 * not on it: its verdict is the
 * InputQuality table on this screen. What it cannot do: say
 * anything about the other runs. It is the detail behind one point of the
 * history, so it sits next to the history rather than in place of it.
 * Reports written before 2026-09-26 hold the data drift section only.
 *
 * The report is fetched from the API, never from MinIO: the browser has no
 * storage credentials and must not get any (design doc section 8.2). It is
 * mounted only when asked for, because these reports run to megabytes, and
 * it renders inside a sandboxed iframe so its scripts cannot reach this page.
 *
 * Args:
 *   url: Where the API serves this run's report, or null when the current
 *     client cannot serve one (demo mode).
 *   reportKey: The object key, still shown so it can be found in MinIO.
 *     Null when the run wrote no report at all.
 *   onCopyKey: Called with `reportKey` when the copy button is pressed.
 *
 * Returns:
 *   A JSX element.
 */
export default function EvidentlyReport({ url, reportKey, onCopyKey }) {
  const [open, setOpen] = useState(false);

  if (!reportKey) {
    return (
      <div className="evidently-placeholder">
        <p>
          Lần đo này <b>không sinh báo cáo Evidently</b> — cửa sổ theo dõi có dưới 50 dự đoán, quá ít để đo, nên
          monitor dừng trước khi chạy Evidently và mọi mục là &ldquo;chưa đủ dữ liệu&rdquo;.
        </p>
      </div>
    );
  }

  return (
    <div className="evidently-box">
      <div className="evidently-head">
        <div>
          <p className="evidently-title">
            <FileBarChart size={15} /> Báo cáo Evidently (chi tiết lần đo)
          </p>
          <p className="evidently-sub">
            Chi tiết của <b>riêng lần đo này</b>, không có lịch sử: data drift, tổng quan từng cột, prediction
            drift và performance (khi có đủ ground truth). Ở phần performance, &ldquo;current&rdquo; là traffic thật
            còn &ldquo;reference&rdquo; là tập test, vẽ chồng lên nhau. Chất lượng input xem ở bảng phía trên. Báo cáo
            viết trước ngày 26/9/2026 chỉ có phần data drift.
          </p>
          <p className="evidently-sub">
            Evidently chỉ kết luận theo <b>tỉ lệ cột bị lệch</b> (ngưỡng 0,5), nên nó có thể ghi &ldquo;Dataset Drift
            is NOT detected&rdquo; trong khi ô Data drift ở trên báo cảnh báo: mức đó do hệ thống tự xếp, còn tính
            thêm luật độ lớn, vốn sinh ra để bắt trường hợp drift dồn vào một hai cột.
          </p>
        </div>
        <div className="evidently-actions">
          {url && (
            <button className="btn-secondary" onClick={() => setOpen((value) => !value)}>
              {open ? "Ẩn báo cáo" : "Xem báo cáo"}
            </button>
          )}
          {url && (
            <a className="btn-secondary" href={url} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Tab mới
            </a>
          )}
        </div>
      </div>

      {open && url && (
        // allow-scripts without allow-same-origin: Evidently's charts need
        // JavaScript, but the report stays in an opaque origin and cannot
        // touch this page or its storage.
        <iframe
          className="evidently-frame"
          src={url}
          sandbox="allow-scripts"
          title="Báo cáo Evidently"
        />
      )}

      {!url && <p className="hint-note">Chế độ minh hoạ không có báo cáo thật để hiển thị.</p>}

      <div className="report-key-row">
        <code>{reportKey}</code>
        <button className="icon-btn" onClick={() => onCopyKey(reportKey)} aria-label="Sao chép">
          <Copy size={14} />
        </button>
      </div>
    </div>
  );
}
