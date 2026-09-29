// frontend/src/hooks/worker/useWorkerEquipment.js
import { useQuery } from "@tanstack/react-query";
import { fetchWorkerEquipment } from "@/lib/worker/api";
import { getTodayMsk } from "@/lib/worker/time";

export function useWorkerEquipment(workerId, date) {
  const targetDate = date || getTodayMsk();

  return useQuery({
    queryKey: ["workerEquipment", workerId, targetDate],
    queryFn: () => fetchWorkerEquipment(workerId, targetDate),
    enabled: Boolean(workerId),
    staleTime: 30000,
  });
}
