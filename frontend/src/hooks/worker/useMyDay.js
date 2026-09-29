// frontend/src/hooks/worker/useMyDay.js
import { useQuery } from "@tanstack/react-query";
import { fetchMyDay } from "@/lib/worker/api";
import { getTodayMsk } from "@/lib/worker/time";

export function useMyDay(date) {
  const targetDate = date || getTodayMsk();

  return useQuery({
    queryKey: ["myDay", targetDate],
    queryFn: () => fetchMyDay(targetDate),
    refetchInterval: 60000,
    refetchOnWindowFocus: true,
    staleTime: 15000,
    retry: 2,
  });
}
