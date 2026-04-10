import { useState, useEffect, useCallback } from "react";
import { questionsApi, type Question } from "../api/client";

export function useQuestions(params?: Record<string, string>) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const key = JSON.stringify(params);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await questionsApi.list(params);
      setQuestions(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  return { questions, loading, error, reload: load };
}
