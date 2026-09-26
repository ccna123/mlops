// Demo-mode stand-in for src/lib/api.js's `api` object. Same method
// signatures, same ApiError shape, so every page can call whichever one
// `useClient()` (src/lib/useClient.js) hands it without branching internally.
import { ApiError } from "./api";
import * as fx from "./demoFixtures";
import { STAGE_ORDER } from "./constants";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const demoApi = {
  health: async () => {
    await delay(150);
    return fx.health;
  },

  triggerRun: async (payload) => {
    await delay(300);
    return {
      run_id: `manual__${new Date().toISOString()}`,
      dag_id: "ml_pipeline",
      state: "queued",
      _demoTaskType: payload.task_type,
    };
  },

  listEstimators: async () => {
    await delay(120);
    return fx.estimators;
  },

  listRuns: async () => {
    await delay(200);
    return fx.runs;
  },

  getRun: async (runId) => {
    await delay(200);
    return (
      fx.runDetails[runId] ?? {
        run_id: runId,
        state: "queued",
        tasks: STAGE_ORDER.map((task_id) => ({ task_id, state: null, try_number: 0, duration: null })),
      }
    );
  },

  uploadDataset: async (file, datasetVersion, onProgress) => {
    for (let progress = 0.2; progress <= 1; progress += 0.2) {
      await delay(120);
      onProgress?.(progress);
    }
    return {
      dataset_version: datasetVersion,
      rows: 4,
      size_mb: 0.01,
      split_points: { original: { t1: "2023-11-02", t2: "2024-10-15", undated_test_share: 0.2 } },
    };
  },

  getPreview: async (datasetVersion) => {
    await delay(400);
    if (datasetVersion !== "v1") {
      throw new ApiError("notfound", 404, `no dataset at version ${datasetVersion}`);
    }
    return fx.preview;
  },

  listModels: async () => {
    await delay(200);
    return fx.models;
  },

  promote: async (name, version) => {
    await delay(300);
    return { name, version, alias: "champion", serving: { switched: true, version, error: null } };
  },

  modelCard: async (name, version) => {
    await delay(200);
    return { ...fx.modelCard, model_name: name, version };
  },

  feedbackPreview: async (taskType) => {
    await delay(300);
    return { ...fx.feedbackPreview, task_type: taskType };
  },

  feedbackRun: async () => {
    await delay(300);
    return { run_id: `manual__${new Date().toISOString()}`, dag_id: "feedback_data_pipeline", state: "queued" };
  },

  feedbackStatus: async () => {
    await delay(150);
    return { run: null };
  },

  deleteModelVersion: async (name, version) => {
    await delay(300);
    return { name, version, deleted: true };
  },

  deleteModel: async (name) => {
    await delay(300);
    return { name, deleted: true, serving: { switched: true, version: null, error: null } };
  },

  listScenarios: async () => {
    await delay(120);
    return fx.scenarios;
  },

  // Demo mode has no Airflow, so the traffic run is faked as one that already
  // finished: the screen must still be able to show the "done" state.
  simulate: async () => {
    await delay(300);
    return { run_id: `manual__${new Date().toISOString()}`, dag_id: "traffic_agent", state: "queued" };
  },

  simulateStatus: async () => {
    await delay(150);
    return {
      run: {
        run_id: "manual__2026-09-22T10:00:00+00:00",
        state: "success",
        task_type: "regression",
        started_at: "2026-09-22T10:00:00+00:00",
        ended_at: "2026-09-22T10:01:12+00:00",
      },
    };
  },

  triggerDriftRun: async () => {
    await delay(300);
    return { run_id: `manual__${new Date().toISOString()}`, dag_id: "monitoring_dag", state: "queued" };
  },

  driftLatest: async (modelName) => {
    await delay(200);
    const fixture = fx.driftFixturesByModel[modelName];
    if (!fixture) {
      throw new ApiError("notfound", 404, `no drift report yet for ${modelName}`);
    }
    return fixture.latest;
  },

  // Demo mode has no object storage, so there is no report to point at and
  // the component says so instead of showing a broken frame.
  driftReportUrl: () => null,

  driftHistory: async (modelName) => {
    await delay(200);
    const fixture = fx.driftFixturesByModel[modelName];
    return fixture ? fixture.history : { history: [] };
  },
};
