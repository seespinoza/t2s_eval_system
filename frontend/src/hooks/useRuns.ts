import { useState, useEffect, useCallback } from "react";
import { runsApi, type Run } from "../api/client";

export function useRuns(limit = 20) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await runsApi.list(limit);
      setRuns(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  // Poll while any run is in "running" state
  useEffect(() => {
    const hasActive = runs.some((r) => r.status === "running");
    if (!hasActive) return;
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [runs, load]);

  return { runs, loading, error, reload: load };
}

export function useRun(id: string) {
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const data = await runsApi.get(id);
    setRun(data);
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (run?.status !== "running") return;
    const id_ = setInterval(load, 5000);
    return () => clearInterval(id_);
  }, [run, load]);

  return { run, loading, reload: load };
}
