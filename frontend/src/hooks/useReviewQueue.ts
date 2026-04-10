import { useState, useEffect, useCallback } from "react";
import { reviewApi, type ReviewItem } from "../api/client";

export function useReviewQueue(params?: Record<string, string>) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState({ pending: 0, confirmed_pass: 0, override_fail: 0 });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [itemData, statsData] = await Promise.all([
      reviewApi.list(params),
      reviewApi.stats(),
    ]);
    setItems(itemData);
    setStats(statsData);
    setLoading(false);
  }, [JSON.stringify(params)]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const submit = async (id: string, decision: string, reviewer?: string, notes?: string) => {
    await reviewApi.submit(id, { decision, reviewer, notes });
    load();
  };

  return { items, stats, loading, submit, reload: load };
}
