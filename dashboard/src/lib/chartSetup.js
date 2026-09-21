// Side-effect import: registers the Chart.js pieces DriftHistoryChart needs.
// Imported once, from src/pages/Drift.jsx.
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);
