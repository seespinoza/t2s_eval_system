import { useState, useEffect } from "react";
import { metricsApi, type RunMetrics, type TimeseriesPoint } from "../api/client";

export function useRunMetrics(runId: string) {
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  useEffect(() => {
    metricsApi.breakdown(runId).then(setMetrics as any).catch(() => {});
  }, [runId]);
  return metrics;
}

export function useCompareMetrics(runIds: string[]) {
  const [data, setData] = useState<RunMetrics[]>([]);
  const key = runIds.join(",");
  useEffect(() => {
    if (!runIds.length) return;
    metricsApi.compare(runIds).then(setData).catch(() => {});
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return data;
}

export function useTimeseries() {
  const [data, setData] = useState<TimeseriesPoint[]>([]);
  useEffect(() => {
    metricsApi.timeseries().then(setData).catch(() => {});
  }, []);
  return data;
}
