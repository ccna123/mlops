import { useRef, useState } from "react";
import { UploadCloud, Eye } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { formatNumber, formatPercent } from "../lib/format";
import { MAX_UPLOAD_BYTES, DATASET_VERSION_PATTERN } from "../lib/constants";
import { ApiError } from "../lib/api";

const ROW_LIMIT_OPTIONS = [10, 50, 100, 200];

/**
 * Renders the Dữ liệu screen: upload a new dataset version and preview an
 * existing one (brief §4.3).
 *
 * Args:
 *   None. Reads the API client from DemoModeContext.
 *
 * Returns:
 *   A JSX page element.
 */
export default function DataPage() {
  const client = useClient();
  const pushToast = useToast();

  const [file, setFile] = useState(null);
  const [uploadVersion, setUploadVersion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [convertingPhase, setConvertingPhase] = useState(false);
  const [overwriteDialog, setOverwriteDialog] = useState(null);
  const fileInputRef = useRef(null);

  const [previewVersionInput, setPreviewVersionInput] = useState("v1");
  const [previewState, setPreviewState] = useState({ status: "empty" });
  const [rowLimit, setRowLimit] = useState(50);

  const versionValid = uploadVersion.length > 0 && DATASET_VERSION_PATTERN.test(uploadVersion);
  const fileValid = Boolean(file) && file.name.toLowerCase().endsWith(".csv");
  const sizeValid = !file || file.size <= MAX_UPLOAD_BYTES;
  const canUpload = fileValid && versionValid && sizeValid && !uploading;

  // Checks whether the target version already exists via a cheap
  // rows=1 preview before actually uploading, per brief §4.3 — the API has
  // no 409, so a silent overwrite needs this client-side confirmation gate.
  async function startUploadFlow() {
    if (!canUpload) return;
    try {
      await client.getPreview(uploadVersion, 1);
      setOverwriteDialog({ kind: "exists" });
    } catch (error) {
      if (error instanceof ApiError && error.kind === "notfound") {
        doUpload();
      } else {
        setOverwriteDialog({ kind: "unknown" });
      }
    }
  }

  async function doUpload() {
    setOverwriteDialog(null);
    setUploading(true);
    setUploadProgress(0);
    setConvertingPhase(false);
    try {
      const result = await client.uploadDataset(file, uploadVersion, (progress) => {
        setUploadProgress(progress);
        if (progress >= 1) setConvertingPhase(true);
      });
      pushToast({
        type: "success",
        text: `Đã tải lên ${result.rows} dòng vào phiên bản ${result.dataset_version} (${result.size_mb} MB parquet)`,
      });
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({ type: "error", text: `Tải lên thất bại: ${typeof detail === "string" ? detail : "lỗi không xác định"}` });
    } finally {
      setUploading(false);
      setConvertingPhase(false);
    }
  }

  async function loadPreview() {
    if (!previewVersionInput) return;
    setPreviewState({ status: "loading" });
    try {
      const body = await client.getPreview(previewVersionInput, 200);
      setPreviewState({ status: "data", ...body });
      setRowLimit(Math.min(50, body.sample.length || 50));
    } catch (error) {
      if (error instanceof ApiError && error.kind === "notfound") {
        setPreviewState({ status: "notfound", detail: error.detail });
      } else if (error instanceof ApiError && error.kind === "validation") {
        setPreviewState({ status: "validation", detail: error.detail });
      } else {
        setPreviewState({ status: "error", error });
      }
    }
  }

  const columns = previewState.status === "data" ? Object.keys(previewState.sample[0] ?? {}) : [];

  return (
    <div className="page-grid">
      <section className="card">
        <div className="section-head">
          <div>
            <h2>Tải CSV</h2>
            <p className="section-sub">Tạo một phiên bản dữ liệu mới. Chỉ nhận file .csv.</p>
          </div>
        </div>

        <label className="drop-zone">
          <UploadCloud size={22} />
          {file ? file.name : "Kéo CSV vào đây hoặc chọn file"}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {file && !fileValid && <p className="field-error">Chỉ nhận file .csv.</p>}
        {file && fileValid && !sizeValid && (
          <p className="field-error">
            File vượt trần 500 MiB ({formatNumber(file.size / 1024 / 1024)} MB) — không thể tải lên.
          </p>
        )}

        <label className="field">
          <span>Phiên bản đích *</span>
          <input value={uploadVersion} onChange={(event) => setUploadVersion(event.target.value)} placeholder="ví dụ v2" />
        </label>
        {uploadVersion && !versionValid && (
          <p className="field-error">Chỉ chữ, số, dấu chấm, gạch dưới, gạch nối; bắt đầu bằng chữ hoặc số; tối đa 64 ký tự.</p>
        )}

        <button className="btn-primary" disabled={!canUpload} onClick={startUploadFlow}>
          Tải lên
        </button>

        {uploading && (
          <div className="upload-progress">
            <div className="progress-track">
              <div className="progress-bar" style={{ width: `${Math.round(uploadProgress * 100)}%` }} />
            </div>
            <p>{convertingPhase ? "Đang chuyển sang parquet…" : `Đang tải lên… ${Math.round(uploadProgress * 100)}%`}</p>
          </div>
        )}
        <p className="hint-note">Ghi đè một phiên bản đã tồn tại sẽ hỏi xác nhận trước khi gửi.</p>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Xem trước dữ liệu</h2>
            <p className="section-sub">Chỉ tải khi mở màn này hoặc bấm xem — không poll.</p>
          </div>
        </div>
        <div className="filters">
          <input value={previewVersionInput} onChange={(event) => setPreviewVersionInput(event.target.value)} placeholder="v1" />
          <button className="btn-secondary" onClick={loadPreview}>
            <Eye size={14} /> Xem dữ liệu
          </button>
        </div>

        {previewState.status === "empty" && <EmptyState title="Nhập phiên bản dữ liệu để xem, hoặc tải một CSV lên." />}
        {previewState.status === "loading" && <LoadingSkeleton rows={4} />}
        {previewState.status === "notfound" && (
          <EmptyState
            title={`Chưa có dữ liệu ở phiên bản này (${previewVersionInput}).`}
            description={previewState.detail}
            action={
              <button className="btn-secondary" onClick={() => setUploadVersion(previewVersionInput)}>
                Tải lên phiên bản này
              </button>
            }
          />
        )}
        {previewState.status === "validation" && (
          <p className="field-error">
            {Array.isArray(previewState.detail)
              ? previewState.detail.map((item, index) => <span key={index}>{item.msg} </span>)
              : previewState.detail}
          </p>
        )}
        {previewState.status === "error" && <ErrorState kind="system" detail={previewState.error.detail} onRetry={loadPreview} />}
        {previewState.status === "data" && (
          <p className="statsline">
            Thống kê trên{" "}
            <b>
              {formatNumber(previewState.stats_rows)} / {formatNumber(previewState.total_rows)} dòng
            </b>
          </p>
        )}
      </section>

      {previewState.status === "data" && (
        <>
          <section className="card card-wide">
            <div className="section-head">
              <div>
                <h2>Dòng mẫu</h2>
                <p className="section-sub">Dữ liệu thô — giá trị không được chuẩn hóa.</p>
              </div>
              <select value={rowLimit} onChange={(event) => setRowLimit(Number(event.target.value))}>
                {ROW_LIMIT_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option} dòng
                  </option>
                ))}
              </select>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewState.sample.slice(0, rowLimit).map((row, index) => (
                    <tr key={index}>
                      {columns.map((column) => (
                        <td key={column}>{row[column] === "" ? <span className="blank-chip">(trống)</span> : row[column]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card card-wide">
            <div className="section-head">
              <div>
                <h2>Chất lượng cột</h2>
                <p className="section-sub">Tỷ lệ thiếu (đếm cả chuỗi rỗng) và số dòng ngoài biên, trong mẫu thống kê.</p>
              </div>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>CỘT</th>
                    <th>LOẠI</th>
                    <th>THIẾU</th>
                    <th>NGOÀI BIÊN</th>
                  </tr>
                </thead>
                <tbody>
                  {previewState.columns.map((column) => (
                    <tr key={column.name}>
                      <td>{column.name}</td>
                      <td>
                        <span className="kind-chip">{column.kind}</span>
                      </td>
                      <td>
                        <div className="meter">
                          <i style={{ width: `${column.missing_rate * 100}%` }} />
                          <span>{formatPercent(column.missing_rate)}</span>
                        </div>
                      </td>
                      <td>{formatNumber(column.out_of_bounds)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {overwriteDialog?.kind === "exists" && (
        <ConfirmDialog
          title="Ghi đè phiên bản đã tồn tại?"
          confirmLabel="Ghi đè và tải lên"
          danger
          busy={uploading}
          onConfirm={doUpload}
          onCancel={() => setOverwriteDialog(null)}
        >
          <p>
            Phiên bản <b>{uploadVersion}</b> đã tồn tại. Tải lên sẽ <b>ghi đè âm thầm</b> dữ liệu cũ, không thể hoàn tác.
          </p>
        </ConfirmDialog>
      )}
      {overwriteDialog?.kind === "unknown" && (
        <ConfirmDialog
          title="Không xác định được phiên bản này đã tồn tại chưa"
          confirmLabel="Vẫn tải lên"
          danger
          busy={uploading}
          onConfirm={doUpload}
          onCancel={() => setOverwriteDialog(null)}
        >
          <p>
            Không kiểm tra được phiên bản <b>{uploadVersion}</b> đã tồn tại hay chưa. Nếu nó đã tồn tại, tải lên sẽ ghi đè âm thầm.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
