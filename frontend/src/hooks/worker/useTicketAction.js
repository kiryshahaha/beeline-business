// frontend/src/hooks/worker/useTicketAction.js
import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { workerAction } from "@/lib/worker/api";

function generateUUID() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `act-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useTicketAction() {
  const qc = useQueryClient();
  const keyRef = useRef(null);

  const mutation = useMutation({
    mutationFn: ({ path, body }) => {
      keyRef.current ??= generateUUID();
      return workerAction(path, body, keyRef.current);
    },
    onSuccess: (data, variables) => {
      keyRef.current = null;
      qc.invalidateQueries({ queryKey: ["myDay"] });
      if (variables?.ticketId) {
        qc.invalidateQueries({ queryKey: ["ticketChanges", variables.ticketId] });
        qc.invalidateQueries({ queryKey: ["ticket", variables.ticketId] });
      }
    },
    onError: (e, variables) => {
      if (e.status === 409 || e.status === 404) {
        keyRef.current = null;
        qc.invalidateQueries({ queryKey: ["myDay"] });
        if (variables?.ticketId) {
          qc.invalidateQueries({ queryKey: ["ticketChanges", variables.ticketId] });
          qc.invalidateQueries({ queryKey: ["ticket", variables.ticketId] });
        }
      }
    },
  });

  const resetKey = () => {
    keyRef.current = null;
  };

  return {
    ...mutation,
    resetKey,
  };
}
