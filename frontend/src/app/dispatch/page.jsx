"use client";

import React, {
  useState,
  useMemo,
  useCallback,
  useRef,
  useEffect,
} from "react";
import styles from "./page.module.css";
import { useSchedule } from "@/hooks/useSchedule";
import { useBrigades } from "@/hooks/useBrigades";
import { useWorkTypes } from "@/hooks/useWorkTypes";
import { useUsers } from "@/hooks/useUsers";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";
import DatePicker from "@/components/ui/DatePicker/DatePicker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAvailableDates } from "@/hooks/useAvailableDates";

/* ────────────────────────────────────────────
   Helpers
   ──────────────────────────────────────────── */

function getMskTodayStr() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
}

function fmtTime(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return `${d.getHours().toString().padStart(2, "0")}:${d
    .getMinutes()
    .toString()
    .padStart(2, "0")}`;
}

function getInitials(fullName = "") {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0][0]?.toUpperCase() || "?";
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

const TIMELINE_START_HOUR = 6;
const TIMELINE_END_HOUR = 22;
const TOTAL_HOURS = TIMELINE_END_HOUR - TIMELINE_START_HOUR;

function timeToPercent(isoStr) {
  if (!isoStr) return 0;
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return 0;
  const hours = d.getHours() + d.getMinutes() / 60;
  const clamped = Math.max(TIMELINE_START_HOUR, Math.min(TIMELINE_END_HOUR, hours));
  return ((clamped - TIMELINE_START_HOUR) / TOTAL_HOURS) * 100;
}

function getStatusCategory(ticket) {
  if (!ticket) return "pending";
  const s = String(ticket.status || "").toLowerCase().trim();
  const st = String(ticket.state || "").toLowerCase().trim();
  const combined = `${s} ${st}`;

  if (
    combined.includes("маршрут") ||
    combined.includes("route") ||
    combined.includes("en_route") ||
    combined.includes("moving") ||
    combined.includes("travel") ||
    combined.includes("transit") ||
    combined.includes("пути")
  ) {
    return "route";
  }

  if (
    combined.includes("работ") ||
    combined.includes("progress") ||
    combined.includes("active") ||
    combined.includes("start") ||
    combined.includes("execut")
  ) {
    return "in_progress";
  }

  if (
    combined.includes("выполн") ||
    combined.includes("complet") ||
    combined.includes("done") ||
    combined.includes("finish") ||
    combined.includes("closed") ||
    combined.includes("success")
  ) {
    return "completed";
  }

  if (
    combined.includes("отмен") ||
    combined.includes("cancel") ||
    combined.includes("wont_fix") ||
    combined.includes("reject") ||
    combined.includes("fail")
  ) {
    return "cancelled";
  }

  return "pending";
}

function getStatusClass(statusCategory) {
  switch (statusCategory) {
    case "in_progress":
      return styles.taskInProgress;
    case "completed":
      return styles.taskCompleted;
    case "cancelled":
      return styles.taskCancelled;
    case "route":
      return styles.taskRoute;
    case "pending":
    default:
      return styles.taskPending;
  }
}

function getStatusLabel(statusCategory) {
  switch (statusCategory) {
    case "in_progress":
      return "В работе";
    case "completed":
      return "Выполнена";
    case "cancelled":
      return "Отменена";
    case "route":
      return "Маршрут";
    case "pending":
    default:
      return "Ожидает";
  }
}

function getCategoryClass(category) {
  switch (category) {
    case "emergency":
      return styles.taskEmergency;
    case "additional":
      return styles.taskAdditional;
    case "connection":
      return styles.taskConnection;
    case "repair":
      return styles.taskRepair;
    case "maintenance":
      return styles.taskMaintenance;
    case "disconnection":
      return styles.taskDisconnection;
    default:
      return styles.taskOther;
  }
}

function getCategoryLabel(category) {
  switch (category) {
    case "emergency":
      return "Аварийная";
    case "additional":
      return "Дополнительная";
    case "connection":
      return "Подключение";
    case "repair":
      return "Ремонт";
    case "maintenance":
      return "Обслуживание";
    case "disconnection":
      return "Отключение";
    default:
      return "Другое";
  }
}

function formatAssignError(errData) {
  if (!errData) return "Не удалось назначить заявку";
  const detail = errData.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;

  if (Array.isArray(detail?.violations) && detail.violations.length > 0) {
    const v = detail.violations[0];
    const code = v.code || v.category;
    const descriptions = {
      equipment_not_reserved: "Для этой заявки требуется оборудование, которое еще не зарезервировано на складе",
      equipment_held_by_worker: "Оборудование по заявке закреплено за другим инженером (требуется возврат/списание)",
      equipment_not_on_hand: "У инженера нет нужного оборудования на руках",
      worker_off_line: "Инженер снят с линии",
      service_area_mismatch: "Инженер принадлежит другому участку обслуживания",
      skill_mismatch: "У инженера нет необходимых навыков для этого вида работ",
      shift_not_found: "У инженера нет смены в этот день",
      capacity_exceeded: "Превышена загрузка инженера",
      outside_shift: "Время заявки выходит за рамки смены инженера",
    };
    return descriptions[code] || `Назначение отклонено: ${code}`;
  }

  if (detail?.code) {
    const descriptions = {
      manual_assignment_rejected: "Назначение отклонено правилами планирования",
      service_area_mismatch: "Инженер принадлежит другому участку обслуживания",
      worker_off_line: "Инженер снят с линии",
    };
    return descriptions[detail.code] || `Ошибка: ${detail.code}`;
  }

  return "Не удалось назначить заявку инженеру";
}

const TIME_SLOTS = Array.from(
  { length: TOTAL_HOURS + 1 },
  (_, i) => TIMELINE_START_HOUR + i
);

/* ────────────────────────────────────────────
   Component
   ──────────────────────────────────────────── */

export default function DispatchPage() {
  const todayStr = useMemo(() => getMskTodayStr(), []);
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isForeman = user?.role === "foreman";

  /* ── State ── */
  const [dateValue, setDateValue] = useState({
    mode: "single",
    date: todayStr,
    from: todayStr,
    to: todayStr,
  });

  const { hasToday, closestDate } = useAvailableDates(todayStr);

  // Автоматический выбор ближайшего доступного дня, если на сегодня нет задач
  useEffect(() => {
    if (!hasToday && closestDate && closestDate !== todayStr) {
      queueMicrotask(() => {
        setDateValue((prev) => {
          if (prev.mode === "single" && prev.date === todayStr) {
            return { mode: "single", date: closestDate, from: closestDate, to: closestDate };
          }
          return prev;
        });
      });
    }
  }, [hasToday, closestDate, todayStr]);
  const [selectedBrigadeId, setSelectedBrigadeId] = useState("all");
  const [selectedWorkType, setSelectedWorkType] = useState("all");
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [lockedOverrides, setLockedOverrides] = useState(new Map());
  const [redistPool, setRedistPool] = useState([]); // tasks moved to redistribution
  const [draggedTask, setDraggedTask] = useState(null);
  const [dragOverWorkerId, setDragOverWorkerId] = useState(null);
  const [dragOverRedist, setDragOverRedist] = useState(false);
  const [contextMenu, setContextMenu] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [showRedistZone, setShowRedistZone] = useState(true);
  const [isReplanning, setIsReplanning] = useState(false);
  const [isAssigning, setIsAssigning] = useState(false);
  const [assigningText, setAssigningText] = useState("Обновление назначения…");
  const [assignError, setAssignError] = useState(null);

  const contextMenuRef = useRef(null);
  const tooltipOpenTimeout = useRef(null);
  const tooltipCloseTimeout = useRef(null);
  const draggedTaskRef = useRef(null);
  // Counter-based drag tracking to avoid flickering from child elements
  const workerDragCounters = useRef(new Map());
  const redistDragCounter = useRef(0);

  /* ── Data fetching ── */
  const { schedule, isLoading, isFetching, isError, error } = useSchedule({
    date: dateValue.date || todayStr,
  });

  const handleDateChange = useCallback((newVal) => {
    const newDate = newVal?.date || newVal?.startDate || newVal?.from || todayStr;
    if (newDate && newDate !== dateValue.date) {
      setRedistPool([]);
      setSelectedTaskId(null);
    }
    setDateValue({
      mode: "single",
      date: newDate,
      from: newDate,
      to: newDate,
    });
  }, [dateValue.date, todayStr]);

  const isDateChanging = Boolean(
    (isFetching || isLoading) &&
      dateValue?.date &&
      schedule?.date &&
      dateValue.date !== schedule.date
  );

  const { brigades: brigadesList } = useBrigades();
  const { workTypes } = useWorkTypes();
  const { users: workerUsers = [] } = useUsers({ role: "worker" });

  /* ── Skills catalog & work type rules for qualification matching ── */
  const { data: skillsCatalog = [] } = useQuery({
    queryKey: ["skillsCatalog"],
    queryFn: async () => {
      const res = await apiFetch("/worker/skills");
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 60000,
  });

  const { data: workTypeRules = {} } = useQuery({
    queryKey: ["workTypeRules", workTypes],
    queryFn: async () => {
      const rules = {};
      if (!Array.isArray(workTypes)) return rules;
      await Promise.all(
        workTypes.map(async (wt) => {
          try {
            const res = await apiFetch(`/work-types/${wt.id}/planning-rules`);
            if (res.ok) {
              const data = await res.json();
              rules[wt.id] = data;
              if (wt.name) {
                rules[wt.name.toLowerCase().trim()] = data;
              }
            }
          } catch {}
        })
      );
      return rules;
    },
    enabled: Array.isArray(workTypes) && workTypes.length > 0,
    staleTime: 60000,
  });

  /* ── Close context menu on outside click ── */
  useEffect(() => {
    if (!contextMenu) return;
    const handler = (e) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target)) {
        setContextMenu(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [contextMenu]);

  /* ── Cleanup tooltip timers on unmount ── */
  useEffect(() => {
    return () => {
      if (tooltipOpenTimeout.current) clearTimeout(tooltipOpenTimeout.current);
      if (tooltipCloseTimeout.current) clearTimeout(tooltipCloseTimeout.current);
    };
  }, []);

  /* ── Sync pinned tickets from schedule with optimistic local overrides ── */
  const lockedTaskIds = useMemo(() => {
    const pinned = new Set();
    for (const b of schedule?.brigades || []) {
      for (const w of b.workers || []) {
        for (const t of w.tickets || []) {
          if (t.is_pinned) pinned.add(t.id);
        }
      }
    }
    if (schedule?.unassigned_workers) {
      for (const w of schedule.unassigned_workers) {
        for (const t of w.tickets || []) {
          if (t.is_pinned) pinned.add(t.id);
        }
      }
    }
    for (const [id, isLocked] of lockedOverrides.entries()) {
      if (isLocked) pinned.add(id);
      else pinned.delete(id);
    }
    return pinned;
  }, [schedule, lockedOverrides]);

  /* ── Processed schedule data ── */
  const { brigades, unassignedTickets, allWorkerIds, workerBrigadeMap } = useMemo(() => {
    if (!schedule) return { brigades: [], unassignedTickets: [], allWorkerIds: new Set(), workerBrigadeMap: new Map() };

    const allWorkerIds = new Set();
    const workerBrigadeMap = new Map();

    const brigades = (schedule.brigades || []).map((b) => {
      const workers = (b.workers || []).map((w) => {
        allWorkerIds.add(w.id);
        workerBrigadeMap.set(w.id, b.id);
        return {
          ...w,
          brigade_id: b.id,
          brigade_name: b.name,
        };
      });
      return { ...b, workers };
    });

    const unassignedTickets = schedule.unassigned_tickets || [];

    return { brigades, unassignedTickets, allWorkerIds, workerBrigadeMap };
  }, [schedule]);

  /* Combined unassigned tickets without duplicates */
  const combinedUnassignedTickets = useMemo(() => {
    const map = new Map();
    for (const t of unassignedTickets) {
      map.set(t.id, t);
    }
    for (const t of redistPool) {
      if (!map.has(t.id)) {
        map.set(t.id, t);
      }
    }
    return Array.from(map.values());
  }, [unassignedTickets, redistPool]);

  /* ── Filter brigades ── */
  const filteredBrigades = useMemo(() => {
    if (selectedBrigadeId === "all") return brigades;
    return brigades.filter((b) => String(b.id) === selectedBrigadeId);
  }, [brigades, selectedBrigadeId]);

  /* ── Target task being selected or dragged ── */
  const targetTaskId = selectedTaskId || draggedTask?.id;
  const targetTask = (() => {
    if (!targetTaskId) return null;

    // Check brigades -> workers -> tickets
    for (const b of brigades) {
      for (const w of b.workers) {
        for (const t of w.tickets || []) {
          if (t.id === targetTaskId) {
            return {
              ...t,
              sourceWorkerId: w.id,
              sourceWorkerName: w.full_name,
              sourceBrigadeId: b.id,
              office_id: b.office_id,
              // Only constrain to brigade if ticket itself has explicit brigade_id
              brigade_id: t.brigade_id || null,
              service_area_id: t.service_area_id || b.office_id,
            };
          }
        }
      }
    }

    // Check unassigned workers
    if (schedule?.unassigned_workers) {
      for (const w of schedule.unassigned_workers) {
        for (const t of w.tickets || []) {
          if (t.id === targetTaskId) {
            return {
              ...t,
              sourceWorkerId: w.id,
              sourceWorkerName: w.full_name,
              sourceBrigadeId: null,
              office_id: null,
              brigade_id: t.brigade_id || null,
              service_area_id: t.service_area_id || null,
            };
          }
        }
      }
    }

    // Check combined unassigned tickets
    const uTask = combinedUnassignedTickets.find((t) => t.id === targetTaskId);
    if (uTask) {
      return {
        ...uTask,
        sourceWorkerId: null,
        start: uTask.start || uTask.visit_window_start,
        end: uTask.end || uTask.visit_window_end,
      };
    }

    return null;
  })();

  /* ── Check if a worker is suitable for targetTask ── */
  const isWorkerSuitable = useCallback(
    (worker, brigade) => {
      if (!targetTask) return true;

      // 1. Worker must be on line
      if (!worker.is_on_line) return false;

      // 2. Worker must be available on that day (not absent or on leave)
      if (worker.day_plan?.availability?.available === false) return false;

      // 3. Service area / Office constraint
      const taskServiceAreaId = targetTask.service_area_id || targetTask.office_id;
      if (taskServiceAreaId && brigade?.office_id && brigade.office_id !== taskServiceAreaId) {
        return false;
      }

      // 4. Brigade constraint ONLY IF ticket is explicitly bound to a brigade
      if (targetTask.brigade_id && brigade?.id && brigade.id !== targetTask.brigade_id) {
        return false;
      }

      // 5. Shift hours coverage
      const taskStartIso = targetTask.start || targetTask.visit_window_start;
      const taskEndIso = targetTask.end || targetTask.visit_window_end;
      const shiftStartIso = worker.day_plan?.shift_start;
      const shiftEndIso = worker.day_plan?.shift_end;

      if (taskStartIso && taskEndIso && shiftStartIso && shiftEndIso) {
        const tStart = new Date(taskStartIso).getTime();
        const tEnd = new Date(taskEndIso).getTime();
        const sStart = new Date(shiftStartIso).getTime();
        const sEnd = new Date(shiftEndIso).getTime();

        if (!isNaN(tStart) && !isNaN(tEnd) && !isNaN(sStart) && !isNaN(sEnd) && sEnd > sStart) {
          if (tStart < sStart || tEnd > sEnd) {
            return false;
          }
        }
      }

      // 6. Skills qualification check
      const workTypeName = targetTask.work_type;
      if (workTypeName && workTypeRules && skillsCatalog.length > 0 && workerUsers.length > 0) {
        const rule =
          workTypeRules[workTypeName.toLowerCase().trim()] ||
          Object.values(workTypeRules).find(
            (r) => r?.name?.toLowerCase() === workTypeName.toLowerCase()
          );

        if (rule?.required_skill_ids && rule.required_skill_ids.length > 0) {
          const userObj = workerUsers.find((u) => u.id === worker.id);
          const userSkills = new Set(
            (userObj?.worker_profile?.skills || []).map((s) => s.toLowerCase().trim())
          );

          for (const skillId of rule.required_skill_ids) {
            const skillItem = skillsCatalog.find((s) => s.id === skillId);
            if (skillItem) {
              const skillName = skillItem.skill.toLowerCase().trim();
              if (!userSkills.has(skillName)) {
                return false;
              }
            }
          }
        }
      }

      return true;
    },
    [targetTask, workTypeRules, skillsCatalog, workerUsers]
  );

  /* ── Set of all eligible worker IDs for targetTask ── */
  const eligibleWorkerIds = useMemo(() => {
    if (!targetTask) return null;

    const eligible = new Set();
    for (const b of brigades) {
      for (const w of b.workers) {
        if (isWorkerSuitable(w, b)) {
          eligible.add(w.id);
        }
      }
    }

    if (schedule?.unassigned_workers) {
      for (const w of schedule.unassigned_workers) {
        if (isWorkerSuitable(w, null)) {
          eligible.add(w.id);
        }
      }
    }

    return eligible;
  }, [targetTask, brigades, schedule, isWorkerSuitable]);

  /* ── Visible brigades (when task clicked, ONLY eligible workers + current worker remain) ── */
  const visibleBrigades = useMemo(() => {
    if (selectedTaskId && eligibleWorkerIds) {
      const sourceWorkerId = targetTask?.sourceWorkerId;
      return filteredBrigades
        .map((b) => ({
          ...b,
          workers: b.workers.filter(
            (w) => eligibleWorkerIds.has(w.id) || (sourceWorkerId && w.id === sourceWorkerId)
          ),
        }))
        .filter((b) => b.workers.length > 0);
    }
    return filteredBrigades;
  }, [filteredBrigades, selectedTaskId, eligibleWorkerIds, targetTask?.sourceWorkerId]);

  /* ── Visible unassigned workers ── */
  const visibleUnassignedWorkers = useMemo(() => {
    const list = schedule?.unassigned_workers || [];
    if (selectedTaskId && eligibleWorkerIds) {
      const sourceWorkerId = targetTask?.sourceWorkerId;
      return list.filter((w) => eligibleWorkerIds.has(w.id) || (sourceWorkerId && w.id === sourceWorkerId));
    }
    return list;
  }, [schedule?.unassigned_workers, selectedTaskId, eligibleWorkerIds, targetTask?.sourceWorkerId]);

  /* ── Work type filter applied to task rendering ── */
  const isTaskVisible = useCallback(
    (ticket) => {
      if (selectedWorkType === "all") return true;
      return ticket.work_type === selectedWorkType;
    },
    [selectedWorkType]
  );

  /* ── Is today selected? ── */
  const isToday = dateValue.date === todayStr;

  /* ── Now indicator position (only for today) ── */
  const nowPercent = useMemo(() => {
    if (!isToday) return null;
    const now = new Date();
    const h = now.getHours() + now.getMinutes() / 60;
    if (h < TIMELINE_START_HOUR || h > TIMELINE_END_HOUR) return null;
    return ((h - TIMELINE_START_HOUR) / TOTAL_HOURS) * 100;
  }, [isToday]);

  /* ── Drag & Drop handlers ── */
  const handleDragStart = useCallback(
    (e, task, workerId) => {
      if (lockedTaskIds.has(task.id)) {
        e.preventDefault();
        return;
      }
      const data = { ...task, sourceWorkerId: workerId };
      draggedTaskRef.current = data;
      setDraggedTask(data);
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", JSON.stringify({ taskId: task.id, sourceWorkerId: workerId }));
    },
    [lockedTaskIds]
  );

  const handleDragEnd = useCallback(() => {
    setTimeout(() => {
      draggedTaskRef.current = null;
      setDraggedTask(null);
    }, 150);
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  /* Counter-based enter/leave to avoid flickering when cursor moves over child nodes */
  const handleWorkerDragEnter = useCallback((e, workerId) => {
    e.preventDefault();
    const count = (workerDragCounters.current.get(workerId) || 0) + 1;
    workerDragCounters.current.set(workerId, count);
    if (count === 1) setDragOverWorkerId(workerId);
  }, []);

  const handleWorkerDragLeave = useCallback((e, workerId) => {
    const count = (workerDragCounters.current.get(workerId) || 1) - 1;
    workerDragCounters.current.set(workerId, Math.max(0, count));
    if (count <= 0) {
      workerDragCounters.current.set(workerId, 0);
      setDragOverWorkerId((prev) => (prev === workerId ? null : prev));
    }
  }, []);

  const handleRedistDragEnter = useCallback((e) => {
    e.preventDefault();
    redistDragCounter.current += 1;
    if (redistDragCounter.current === 1) setDragOverRedist(true);
  }, []);

  const handleRedistDragLeave = useCallback(() => {
    redistDragCounter.current -= 1;
    if (redistDragCounter.current <= 0) {
      redistDragCounter.current = 0;
      setDragOverRedist(false);
    }
  }, []);

  /* Drop on worker → reassign */
  /* ── Assign task to worker (by click or drop) ── */
  const handleAssignToWorker = useCallback(
    async (taskId, targetWorkerId) => {
      if (!taskId || !targetWorkerId) return;

      if (isForeman) {
        setAssignError("У бригадира режим только просмотра. Назначение доступно наблюдателю.");
        setTimeout(() => setAssignError(null), 5000);
        return;
      }

      if (eligibleWorkerIds && !eligibleWorkerIds.has(targetWorkerId)) {
        setAssignError("Этот инженер не подходит для выбранной заявки");
        setTimeout(() => setAssignError(null), 5000);
        return;
      }

      const sourceWorkerId = targetTask?.sourceWorkerId;
      if (sourceWorkerId === targetWorkerId) {
        draggedTaskRef.current = null;
        setDraggedTask(null);
        setSelectedTaskId(null);
        return;
      }

      setIsAssigning(true);
      setAssigningText("Назначение заявки инженеру…");
      try {
        const res = await apiFetch(`/tickets/${taskId}/assignees`, {
          method: "PUT",
          body: JSON.stringify({
            worker_id: targetWorkerId,
            is_pinned: lockedTaskIds.has(taskId),
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const msg = formatAssignError(errData);
          setAssignError(msg);
          setTimeout(() => setAssignError(null), 6000);
        } else {
          setAssignError(null);
          await queryClient.invalidateQueries({ queryKey: ["schedule"] });
          setRedistPool((prev) => prev.filter((t) => t.id !== taskId));
        }
      } catch (err) {
        console.error("Failed to assign task:", err);
        setAssignError("Ошибка связи с сервером при назначении заявки");
        setTimeout(() => setAssignError(null), 6000);
      } finally {
        setIsAssigning(false);
      }

      draggedTaskRef.current = null;
      setDraggedTask(null);
      setSelectedTaskId(null);
    },
    [isForeman, eligibleWorkerIds, targetTask?.sourceWorkerId, lockedTaskIds, queryClient]
  );

  /* Drop on worker → reassign */
  const handleDropOnWorker = useCallback(
    async (e, targetWorkerId) => {
      if (e) e.preventDefault();
      setDragOverWorkerId(null);

      let task = draggedTaskRef.current || draggedTask;
      let taskId = task?.id || selectedTaskId;

      if (!taskId && e?.dataTransfer) {
        try {
          const raw = e.dataTransfer.getData("text/plain");
          if (raw) {
            const parsed = JSON.parse(raw);
            taskId = parsed.taskId;
          }
        } catch {}
      }

      if (!taskId) return;
      handleAssignToWorker(taskId, targetWorkerId);
    },
    [draggedTask, selectedTaskId, handleAssignToWorker]
  );

  /* Drop on redistribution zone → unassign */
  const handleDropOnRedist = useCallback(
    async (e) => {
      e.preventDefault();
      setDragOverRedist(false);

      if (isForeman) {
        setAssignError("У бригадира режим только просмотра. Перераспределение доступно наблюдателю.");
        setTimeout(() => setAssignError(null), 5000);
        return;
      }

      let task = draggedTaskRef.current || draggedTask;
      let taskId = task?.id;

      if (!taskId && e.dataTransfer) {
        try {
          const raw = e.dataTransfer.getData("text/plain");
          if (raw) {
            const parsed = JSON.parse(raw);
            taskId = parsed.taskId;
          }
        } catch {}
      }

      if (!taskId) return;

      // Find full task info
      let fullTask = null;
      for (const b of brigades) {
        for (const w of b.workers) {
          for (const t of w.tickets || []) {
            if (t.id === taskId) {
              fullTask = { ...t, brigade_id: b.id, worker_name: w.full_name };
              break;
            }
          }
          if (fullTask) break;
        }
        if (fullTask) break;
      }

      if (!fullTask && schedule?.unassigned_workers) {
        for (const w of schedule.unassigned_workers) {
          for (const t of w.tickets || []) {
            if (t.id === taskId) {
              fullTask = { ...t, worker_name: w.full_name };
              break;
            }
          }
          if (fullTask) break;
        }
      }

      if (fullTask && !redistPool.find((t) => t.id === taskId)) {
        setRedistPool((prev) => [...prev, fullTask]);
      }

      try {
        const res = await apiFetch(`/tickets/${taskId}/assignees`, {
          method: "PUT",
          body: JSON.stringify({
            worker_id: null,
            is_pinned: false,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const detail = errData?.detail;
          const msg =
            typeof detail === "string"
              ? detail
              : detail?.message || "Не удалось вернуть заявку в пул";
          setAssignError(msg);
          setTimeout(() => setAssignError(null), 6000);
          setRedistPool((prev) => prev.filter((t) => t.id !== taskId));
        } else {
          setAssignError(null);
          await queryClient.invalidateQueries({ queryKey: ["schedule"] });
          setLockedOverrides((prev) => {
            const next = new Map(prev);
            next.delete(taskId);
            return next;
          });
        }
      } catch (err) {
        console.error("Failed to unassign task:", err);
      }

      draggedTaskRef.current = null;
      setDraggedTask(null);
      setSelectedTaskId(null);
    },
    [isForeman, draggedTask, brigades, schedule, redistPool, queryClient]
  );

  /* Wrappers that reset counters before calling the real drop handlers */
  const handleWorkerDrop = useCallback(
    (e, workerId) => {
      workerDragCounters.current.set(workerId, 0);
      handleDropOnWorker(e, workerId);
    },
    [handleDropOnWorker]
  );

  const handleRedistDrop = useCallback(
    (e) => {
      redistDragCounter.current = 0;
      handleDropOnRedist(e);
    },
    [handleDropOnRedist]
  );

  /* ── Task click → select & highlight eligible ── */
  const handleTaskClick = useCallback(
    (e, task) => {
      e.preventDefault();
      e.stopPropagation();
      e.nativeEvent?.stopImmediatePropagation?.();
      setSelectedTaskId((prev) => (prev === task.id ? null : task.id));
      setTooltip(null);
      setContextMenu(null);
    },
    []
  );

  /* ── Task right-click context menu ── */
  const handleTaskContextMenu = useCallback(
    (e, task, workerId) => {
      e.preventDefault();
      e.stopPropagation();
      setContextMenu({
        x: e.clientX,
        y: e.clientY,
        task,
        workerId,
      });
    },
    []
  );

  /* ── Lock/unlock task ── */
  const toggleLock = useCallback(
    async (taskId, explicitWorkerId = null) => {
      if (isForeman) {
        setAssignError("У бригадира режим только просмотра. Блокировка доступна наблюдателю.");
        setTimeout(() => setAssignError(null), 5000);
        return;
      }

      const isCurrentlyLocked = lockedTaskIds.has(taskId);
      setLockedOverrides((prev) => {
        const next = new Map(prev);
        next.set(taskId, !isCurrentlyLocked);
        return next;
      });

      try {
        let workerId = explicitWorkerId;
        if (!workerId) {
          for (const b of brigades) {
            for (const w of b.workers) {
              for (const t of w.tickets || []) {
                if (t.id === taskId) {
                  workerId = w.id;
                  break;
                }
              }
              if (workerId) break;
            }
            if (workerId) break;
          }
        }
        if (!workerId && schedule?.unassigned_workers) {
          for (const w of schedule.unassigned_workers) {
            for (const t of (w.tickets || [])) {
              if (t.id === taskId) {
                workerId = w.id;
                break;
              }
            }
            if (workerId) break;
          }
        }

        if (workerId) {
          await apiFetch(`/tickets/${taskId}/assignees`, {
            method: "PUT",
            body: JSON.stringify({
              worker_id: workerId,
              is_pinned: !isCurrentlyLocked,
            }),
          });
          queryClient.invalidateQueries({ queryKey: ["schedule"] });
        }
      } catch (err) {
        console.error("Failed to toggle pin:", err);
        // Revert
        setLockedOverrides((prev) => {
          const next = new Map(prev);
          next.delete(taskId);
          return next;
        });
      }
      setContextMenu(null);
    },
    [isForeman, lockedTaskIds, brigades, schedule, queryClient]
  );

  /* ── Move to redistribution ── */
  const moveToRedist = useCallback(
    async (task, workerId) => {
      if (isForeman) {
        setAssignError("У бригадира режим только просмотра. Перераспределение доступно наблюдателю.");
        setTimeout(() => setAssignError(null), 5000);
        return;
      }

      let brigadeId = null;
      for (const b of brigades) {
        for (const w of b.workers) {
          if (w.id === workerId) {
            brigadeId = b.id;
            break;
          }
        }
        if (brigadeId) break;
      }

      if (!redistPool.find((t) => t.id === task.id)) {
        setRedistPool((prev) => [...prev, { ...task, brigade_id: brigadeId }]);
      }

      setIsAssigning(true);
      setAssigningText("Перемещение заявки в пул…");
      try {
        await apiFetch(`/tickets/${task.id}/assignees`, {
          method: "PUT",
          body: JSON.stringify({ worker_id: null, is_pinned: false }),
        });
        await queryClient.invalidateQueries({ queryKey: ["schedule"] });
        setLockedTaskIds((prev) => {
          const next = new Set(prev);
          next.delete(task.id);
          return next;
        });
      } catch (err) {
        console.error("Failed to unassign task:", err);
      } finally {
        setIsAssigning(false);
      }
      setContextMenu(null);
    },
    [isForeman, brigades, redistPool, queryClient]
  );

  /* ── Tooltip on hover ── */
  const handleTaskMouseEnter = useCallback(
    (e, task, worker) => {
      if (tooltipCloseTimeout.current) {
        clearTimeout(tooltipCloseTimeout.current);
        tooltipCloseTimeout.current = null;
      }
      if (tooltipOpenTimeout.current) {
        clearTimeout(tooltipOpenTimeout.current);
      }

      if (tooltip?.task?.id === task.id) return;

      const rect = e.currentTarget?.getBoundingClientRect();
      if (!rect) return;

      tooltipOpenTimeout.current = setTimeout(() => {
        const placeBelow = rect.top < 170;
        const x = Math.max(12, Math.min(rect.left + rect.width / 2 - 140, window.innerWidth - 300));
        const y = placeBelow ? rect.bottom + 8 : rect.top - 8;

        setTooltip({
          x,
          y,
          placeBelow,
          task,
          worker,
        });
      }, 250);
    },
    [tooltip?.task?.id]
  );

  const handleTaskMouseLeave = useCallback(() => {
    if (tooltipOpenTimeout.current) {
      clearTimeout(tooltipOpenTimeout.current);
      tooltipOpenTimeout.current = null;
    }
    if (tooltipCloseTimeout.current) {
      clearTimeout(tooltipCloseTimeout.current);
    }
    tooltipCloseTimeout.current = setTimeout(() => {
      setTooltip(null);
    }, 350);
  }, []);

  const handleTooltipMouseEnter = useCallback(() => {
    if (tooltipCloseTimeout.current) {
      clearTimeout(tooltipCloseTimeout.current);
      tooltipCloseTimeout.current = null;
    }
  }, []);

  const handleTooltipMouseLeave = useCallback(() => {
    if (tooltipCloseTimeout.current) {
      clearTimeout(tooltipCloseTimeout.current);
    }
    tooltipCloseTimeout.current = setTimeout(() => {
      setTooltip(null);
    }, 350);
  }, []);

  /* ── Deselect on background click ── */
  const handleBackgroundClick = useCallback((e) => {
    // Only deselect if clicking directly on the background, not on a task or control
    if (e.target.closest('[data-task-block]') || e.target.closest('[data-no-deselect]')) return;
    setSelectedTaskId(null);
    setContextMenu(null);
    setTooltip(null);
  }, []);

  /* ── Run replan ── */
  const handleRunReplan = useCallback(async () => {
    if (isReplanning) return;
    if (isForeman) {
      setAssignError("У бригадира режим только просмотра. Автоперераспределение доступно наблюдателю.");
      setTimeout(() => setAssignError(null), 5000);
      return;
    }

    setIsReplanning(true);
    setAssignError(null);
    try {
      const revisions = schedule?.plan_revisions || [];
      const routeDate = dateValue.date || todayStr;
      let appliedCount = 0;

      if (revisions.length > 0) {
        // Trigger replan for each service area with revisions
        for (const rev of revisions) {
          try {
            const previewRes = await apiFetch(`/planning/areas/${rev.service_area_id}/${routeDate}/replan/preview`, {
              method: "POST",
              body: JSON.stringify({
                base_day_revision: rev.current_revision || null,
              }),
            });
            if (previewRes.ok) {
              const previewData = await previewRes.json();
              if (previewData?.plan_id) {
                const applyRes = await apiFetch(`/planning/plans/${previewData.plan_id}/apply`, {
                  method: "POST",
                });
                if (applyRes.ok) {
                  appliedCount++;
                }
              }
            }
          } catch (err) {
            console.warn(`Replan preview/apply failed for area ${rev.service_area_id}:`, err);
          }
        }
      } else {
        // Fallback: collect visible service areas from brigades
        const areaIds = new Set();
        for (const b of brigades) {
          if (b.office_id) areaIds.add(b.office_id);
        }
        for (const areaId of areaIds) {
          try {
            const previewRes = await apiFetch(`/planning/areas/${areaId}/${routeDate}/replan/preview`, {
              method: "POST",
              body: JSON.stringify({ base_day_revision: null }),
            });
            if (previewRes.ok) {
              const previewData = await previewRes.json();
              if (previewData?.plan_id) {
                const applyRes = await apiFetch(`/planning/plans/${previewData.plan_id}/apply`, {
                  method: "POST",
                });
                if (applyRes.ok) appliedCount++;
              }
            }
          } catch (err) {
            console.warn(`Fallback replan failed for area ${areaId}:`, err);
          }
        }
      }

      await queryClient.invalidateQueries({ queryKey: ["schedule"] });
      setRedistPool([]);
    } catch (err) {
      console.error("Replan failed:", err);
      setAssignError("Не удалось выполнить автоперераспределение");
      setTimeout(() => setAssignError(null), 6000);
    } finally {
      setIsReplanning(false);
    }
  }, [isReplanning, isForeman, brigades, schedule, dateValue.date, todayStr, queryClient]);

  /* ── Stats ── */
  const stats = useMemo(() => {
    let totalTasks = 0;
    let totalWorkers = 0;
    let conflictsCount = 0;

    for (const b of brigades) {
      for (const w of b.workers) {
        totalWorkers++;
        totalTasks += (w.tickets || []).length;
        conflictsCount += (w.day_plan?.conflicts || []).length;
      }
    }
    for (const w of (schedule?.unassigned_workers || [])) {
      totalWorkers++;
      totalTasks += (w.tickets || []).length;
      conflictsCount += (w.day_plan?.conflicts || []).length;
    }

    return { totalTasks, totalWorkers, unassigned: combinedUnassignedTickets.length, conflictsCount };
  }, [brigades, schedule?.unassigned_workers, combinedUnassignedTickets.length]);

  /* ── Unique work types from schedule ── */
  const scheduleWorkTypes = useMemo(() => {
    const types = new Set();
    for (const b of brigades) {
      for (const w of b.workers) {
        for (const t of w.tickets) {
          if (t.work_type) types.add(t.work_type);
        }
      }
    }
    return [...types].sort();
  }, [brigades]);

  /* ────────────────────────────────────────────
     Render
     ──────────────────────────────────────────── */

  const showOverlay = isLoading || isReplanning || isAssigning || isDateChanging;

  const loadingOverlayText = useMemo(() => {
    if (isReplanning) return "Перераспределение расписания…";
    if (isAssigning) return assigningText;
    if (isDateChanging && dateValue?.date) return `Загрузка расписания на ${dateValue.date}…`;
    return "Загрузка расписания…";
  }, [isReplanning, isAssigning, assigningText, isDateChanging, dateValue?.date]);

  if (isError && !schedule) {
    return (
      <div className={styles.pageWrapper}>
        <div className={styles.loadingWrapper}>
          <span className={styles.errorText}>
            Ошибка: {error?.message || "Не удалось загрузить расписание"}
          </span>
          <button
            className={styles.actionBtn}
            onClick={() => queryClient.invalidateQueries({ queryKey: ["schedule"] })}
          >
            Повторить
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.pageWrapper} onClick={handleBackgroundClick}>
      {/* ── Screen Loading Overlay (darkening overlay with center spinner) ── */}
      {showOverlay && (
        <div className={styles.loadingOverlay} data-no-deselect>
          <div className={styles.loadingOverlayContent}>
            <div className={styles.overlaySpinner} />
            <span className={styles.overlayText}>{loadingOverlayText}</span>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.pageTitle}>Распределение заявок</h1>
        </div>
        <div className={styles.headerRight}>
          {/* Status Legend matching user design */}
          <div className={styles.statusLegend}>
            <span className={styles.legendItem}><i className={styles.dotPending} /> Ожидает</span>
            <span className={styles.legendItem}><i className={styles.dotInProgress} /> В работе</span>
            <span className={styles.legendItem}><i className={styles.dotCompleted} /> Выполнена</span>
            <span className={styles.legendItem}><i className={styles.dotCancelled} /> Отменена</span>
            <span className={styles.legendItem}><i className={styles.lineRoute} /> Маршрут</span>
          </div>

          <div className={styles.statsRow}>
            <div className={styles.statItem}>
              <span className={styles.statDot} style={{ background: "var(--beeline)" }} />
              <span className={styles.statValue}>{stats.totalTasks}</span>
              <span>заявок</span>
            </div>
            <div className={styles.statItem}>
              <span className={styles.statDot} style={{ background: "var(--success)" }} />
              <span className={styles.statValue}>{stats.totalWorkers}</span>
              <span>инженеров</span>
            </div>
            {stats.unassigned > 0 && (
              <div className={styles.statItem}>
                <span className={styles.statDot} style={{ background: "var(--danger)" }} />
                <span className={styles.statValue}>{stats.unassigned}</span>
                <span>без назначения</span>
              </div>
            )}
            {stats.conflictsCount > 0 && (
              <div className={styles.statItem}>
                <span className={styles.statDot} style={{ background: "var(--warning)" }} />
                <span className={styles.statValue}>{stats.conflictsCount}</span>
                <span>конфликтов</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className={styles.filtersBar} onClick={(e) => e.stopPropagation()}>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Дата</span>
          <DatePicker value={dateValue} onChange={handleDateChange} singleOnly />
        </div>

        <div className={styles.filterSeparator} />

        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Бригада</span>
          <select
            className={styles.filterSelect}
            value={selectedBrigadeId}
            onChange={(e) => setSelectedBrigadeId(e.target.value)}
          >
            <option value="all">Все бригады</option>
            {brigades.map((b) => (
              <option key={b.id} value={String(b.id)}>
                {b.name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.filterSeparator} />

        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Вид работ</span>
          <select
            className={styles.filterSelect}
            value={selectedWorkType}
            onChange={(e) => setSelectedWorkType(e.target.value)}
          >
            <option value="all">Все виды</option>
            {scheduleWorkTypes.map((wt) => (
              <option key={wt} value={wt}>
                {wt}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.filterSeparator} />

        <button
          className={`${styles.toggleBtn} ${showRedistZone ? styles.toggleBtnActive : ""}`}
          onClick={() => setShowRedistZone((v) => !v)}
        >
          📦 Зона перераспределения
        </button>

        {isForeman && (
          <div className={styles.foremanReadOnlyBanner}>
            👁️ Режим бригадира (только просмотр)
          </div>
        )}

        <button
          className={`${styles.actionBtnPrimary} ${styles.actionBtn}`}
          onClick={(e) => { e.stopPropagation(); handleRunReplan(); }}
          disabled={isReplanning || isForeman}
          data-no-deselect
          title={isForeman ? "Перераспределение доступно только наблюдателю" : undefined}
        >
          {isReplanning ? (
            <>
              <span className={styles.loadingSpinnerSmall} />
              Перераспределение…
            </>
          ) : (
            <>
              ⚡ Запустить перераспределение
            </>
          )}
        </button>
      </div>

      {/* ── Selection Filter Banner ── */}
      {selectedTaskId && (
        <div
          className={`${styles.filterBanner} ${
            eligibleWorkerIds && eligibleWorkerIds.size === 0 ? styles.noEligibleBanner : ""
          }`}
        >
          <span>
            {eligibleWorkerIds && eligibleWorkerIds.size === 0 ? (
              <span className={styles.noEligibleText}>
                ⚠️ Для заявки #{selectedTaskId}{targetTask?.title ? ` («${targetTask.title}»)` : ""} нет доступных инженеров (не совпадают навыки, смены или участок обслуживания).
              </span>
            ) : (
              <span>
                🎯 Выбрана заявка #{selectedTaskId}{targetTask?.title ? ` («${targetTask.title}»)` : ""}. Доступно подходящих инженеров: {eligibleWorkerIds ? eligibleWorkerIds.size : "…"}. Кликните по инженеру или перетащите для назначения.
              </span>
            )}
          </span>
          <button
            className={styles.clearFilterBtn}
            onClick={() => setSelectedTaskId(null)}
          >
            Снять выбор
          </button>
        </div>
      )}

      {/* ── Empty date notice if 0 tickets on selected date ── */}
      {!isLoading && stats.totalTasks === 0 && stats.unassigned === 0 && (
        <div className={styles.noTasksNotice}>
          <span>ℹ️ На выбранную дату нет запланированных заявок.</span>
          <button
            className={styles.jumpDateBtn}
            onClick={() => handleDateChange({ date: "2026-09-21", startDate: "2026-09-21", endDate: "2026-09-21" })}
          >
            Показать демо-день (21 сен 2026)
          </button>
        </div>
      )}

      {/* ── Error Toast ── */}
      {assignError && (
        <div className={styles.errorToast}>
          <span>⚠️ {assignError}</span>
          <button
            className={styles.errorCloseBtn}
            onClick={() => setAssignError(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Main Timeline ── */}
      <div className={styles.mainContent}>
        <div className={styles.timelineContainer}>
          {/* Time axis header */}
          <div className={styles.timelineHeader}>
            <div className={styles.timelineSidebarHeader}>Инженер</div>
            <div className={styles.timeAxisContainer}>
              {TIME_SLOTS.map((hour) => {
                const nowH = new Date().getHours();
                const isNowHour = isToday && hour === nowH;
                return (
                  <div
                    key={hour}
                    className={`${styles.timeSlot} ${isNowHour ? styles.timeSlotNow : ""}`}
                  >
                    {String(hour).padStart(2, "0")}:00
                  </div>
                );
              })}
            </div>
          </div>

          {/* Brigades and workers */}
          {visibleBrigades.map((brigade) => (
            <React.Fragment key={brigade.id}>
              {/* Brigade separator */}
              <div className={styles.brigadeSeparator}>
                <div className={styles.brigadeSeparatorDot} />
                <span className={styles.brigadeSeparatorName}>{brigade.name}</span>
                <span className={styles.brigadeSeparatorInfo}>
                  {brigade.workers.length} инженер
                  {brigade.workers.length > 1 && brigade.workers.length < 5 ? "а" : "ов"} ·{" "}
                  {brigade.foreman?.full_name || "—"}
                </span>
              </div>

              {/* Workers */}
              {brigade.workers.map((worker) => {
                const isSelectedTaskWorker = targetTask?.sourceWorkerId === worker.id;
                const isEligible = eligibleWorkerIds?.has(worker.id);
                const isDimmed =
                  eligibleWorkerIds !== null && !isEligible && !isSelectedTaskWorker;
                const isDropTarget = dragOverWorkerId === worker.id;
                const isClickable = Boolean(selectedTaskId && isEligible && !isSelectedTaskWorker);

                return (
                  <div
                    key={worker.id}
                    className={`${styles.workerRow} ${
                      isDimmed ? styles.workerRowDimmed : ""
                    } ${isDropTarget ? styles.workerRowDropTarget : ""} ${
                      isEligible ? styles.workerRowHighlighted : ""
                    } ${isClickable ? styles.workerRowClickable : ""}`}
                    title={
                      isClickable
                        ? `Нажмите, чтобы назначить заявку #${selectedTaskId} инженеру ${worker.full_name}`
                        : undefined
                    }
                    onClick={(e) => {
                      if (isClickable) {
                        e.stopPropagation();
                        handleAssignToWorker(selectedTaskId, worker.id);
                      }
                    }}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleWorkerDragEnter(e, worker.id)}
                    onDragLeave={(e) => handleWorkerDragLeave(e, worker.id)}
                    onDrop={(e) => handleWorkerDrop(e, worker.id)}
                  >
                    {/* Worker sidebar */}
                    <div className={styles.workerSidebar}>
                      <div
                        className={`${styles.workerAvatar} ${
                          !worker.is_on_line ? styles.workerAvatarOffline : ""
                        }`}
                      >
                        {getInitials(worker.full_name)}
                        {worker.is_on_line && <div className={styles.onlineIndicator} />}
                      </div>
                      <div className={styles.workerInfo}>
                        <span className={styles.workerName}>{worker.full_name}</span>
                        <span className={styles.workerMeta}>
                          {fmtTime(worker.day_plan?.shift_start)} — {fmtTime(worker.day_plan?.shift_end)}
                          {worker.day_plan?.conflicts?.length > 0 && (
                            <span className={styles.conflictBadge}>
                              {worker.day_plan.conflicts.length} конфл.
                            </span>
                          )}
                        </span>
                        {isSelectedTaskWorker && (
                          <span className={styles.currentWorkerBadge}>Текущий</span>
                        )}
                        {!isSelectedTaskWorker && isEligible && selectedTaskId && (
                          <span className={styles.eligibleBadge}>✓ Подходит</span>
                        )}
                      </div>
                    </div>

                    {/* Worker timeline */}
                    <div className={styles.workerTimeline}>
                      {/* Hour gridlines */}
                      {TIME_SLOTS.map((hour) => (
                        <div
                          key={hour}
                          className={styles.hourGridline}
                          style={{
                            left: `${((hour - TIMELINE_START_HOUR) / TOTAL_HOURS) * 100}%`,
                          }}
                        />
                      ))}

                      {/* Shift background */}
                      {worker.day_plan && (
                        <div
                          className={styles.shiftBackground}
                          style={{
                            left: `${timeToPercent(worker.day_plan.shift_start)}%`,
                            width: `${
                              timeToPercent(worker.day_plan.shift_end) -
                              timeToPercent(worker.day_plan.shift_start)
                            }%`,
                          }}
                        />
                      )}

                      {/* Route travel segments */}
                      {(worker.day_plan?.visits || []).map((visit, vIdx) => {
                        if (!visit.arrival) return null;
                        const arrPct = timeToPercent(visit.arrival);
                        const startPct = timeToPercent(visit.start);
                        if (startPct <= arrPct) return null;
                        const segWidth = Math.max(startPct - arrPct, 1.2);
                        return (
                          <div
                            key={`route-${visit.ticket_id}-${vIdx}`}
                            className={styles.routeSegment}
                            style={{ left: `${arrPct}%`, width: `${segWidth}%` }}
                            title={`В пути к заявке #${visit.ticket_id} (${fmtTime(visit.arrival)} — ${fmtTime(visit.start)}${visit.waiting_minutes > 0 ? `, ожидание ${visit.waiting_minutes} мин` : ""})`}
                          >
                            <span className={styles.routeSegmentLabel}>🚗</span>
                          </div>
                        );
                      })}

                      {/* Now indicator */}
                      {nowPercent !== null && (
                        <div
                          className={styles.nowIndicator}
                          style={{ left: `${nowPercent}%` }}
                        >
                          <div className={styles.nowIndicatorDot} />
                        </div>
                      )}

                      {/* Tasks */}
                      {(worker.tickets || []).map((ticket) => {
                        const isMatchWorkType = isTaskVisible(ticket);
                        const left = timeToPercent(ticket.start);
                        const right = timeToPercent(ticket.end);
                        const width = Math.max(right - left, 3);
                        const isSelected = selectedTaskId === ticket.id;
                        const isLocked = lockedTaskIds.has(ticket.id);
                        const isDragging =
                          draggedTask && draggedTask.id === ticket.id;
                        const isConflicting = (worker.day_plan?.conflicts || []).some((c) =>
                          (c.ticket_ids || []).includes(ticket.id)
                        );

                        // Determine status category matching user legend (Ожидает, В работе, Выполнена, Отменена, Маршрут)
                        const statusCat = getStatusCategory(ticket);

                        return (
                          <div
                            key={ticket.id}
                            data-task-block
                            className={`${styles.taskBlock} ${getStatusClass(statusCat)} ${
                              isSelected ? styles.taskBlockSelected : ""
                            } ${isLocked ? styles.taskBlockLocked : ""} ${
                              isDragging ? styles.taskBlockDragging : ""
                            } ${!isMatchWorkType ? styles.taskBlockDimmedWorkType : ""} ${
                              isConflicting ? styles.taskBlockConflict : ""
                            }`}
                            style={{
                              left: `${left}%`,
                              width: `${width}%`,
                            }}
                            draggable={!isLocked && !isForeman}
                            onDragStart={(e) => handleDragStart(e, ticket, worker.id)}
                            onDragEnd={handleDragEnd}
                            onClick={(e) => handleTaskClick(e, ticket)}
                            onContextMenu={(e) =>
                              handleTaskContextMenu(e, ticket, worker.id)
                            }
                            onMouseEnter={(e) =>
                              handleTaskMouseEnter(e, ticket, worker)
                            }
                            onMouseLeave={handleTaskMouseLeave}
                            title={`#${ticket.id} ${ticket.title}${isConflicting ? " ⚠️ (Конфликт)" : ""}`}
                          >
                            {isLocked && <span className={styles.taskLockIcon}>🔒</span>}
                            <span className={styles.taskTitle}>
                              {width > 5 ? `#${ticket.id}` : ""}
                              {width > 10 ? ` ${ticket.title}` : ""}
                            </span>
                            {width > 8 && (
                              <span className={styles.taskTime}>
                                {fmtTime(ticket.start)}–{fmtTime(ticket.end)}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </React.Fragment>
          ))}

          {/* Unassigned workers (if any) */}
          {visibleUnassignedWorkers.length > 0 && (
            <div className={styles.unassignedSection}>
              <div className={styles.unassignedHeader}>
                Инженеры без бригады ({visibleUnassignedWorkers.length})
              </div>
              {visibleUnassignedWorkers.map((worker) => {
                const isSelectedTaskWorker = targetTask?.sourceWorkerId === worker.id;
                const isEligible = eligibleWorkerIds?.has(worker.id);
                const isDimmed =
                  eligibleWorkerIds !== null && !isEligible && !isSelectedTaskWorker;
                const isDropTarget = dragOverWorkerId === worker.id;
                const isClickable = Boolean(selectedTaskId && isEligible && !isSelectedTaskWorker);

                return (
                  <div
                    key={worker.id}
                    className={`${styles.workerRow} ${
                      isDimmed ? styles.workerRowDimmed : ""
                    } ${isDropTarget ? styles.workerRowDropTarget : ""} ${
                      isEligible ? styles.workerRowHighlighted : ""
                    } ${isClickable ? styles.workerRowClickable : ""}`}
                    title={
                      isClickable
                        ? `Нажмите, чтобы назначить заявку #${selectedTaskId} инженеру ${worker.full_name}`
                        : undefined
                    }
                    onClick={(e) => {
                      if (isClickable) {
                        e.stopPropagation();
                        handleAssignToWorker(selectedTaskId, worker.id);
                      }
                    }}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleWorkerDragEnter(e, worker.id)}
                    onDragLeave={(e) => handleWorkerDragLeave(e, worker.id)}
                    onDrop={(e) => handleWorkerDrop(e, worker.id)}
                  >
                    <div className={styles.workerSidebar}>
                      <div
                        className={`${styles.workerAvatar} ${
                          !worker.is_on_line ? styles.workerAvatarOffline : ""
                        }`}
                      >
                        {getInitials(worker.full_name)}
                        {worker.is_on_line && <div className={styles.onlineIndicator} />}
                      </div>
                      <div className={styles.workerInfo}>
                        <span className={styles.workerName}>{worker.full_name}</span>
                        <span className={styles.workerMeta}>
                          {worker.day_plan?.shift_start
                            ? `${fmtTime(worker.day_plan.shift_start)} — ${fmtTime(worker.day_plan.shift_end)}`
                            : "Без бригады"}
                          {worker.day_plan?.conflicts?.length > 0 && (
                            <span
                              className={`${styles.conflictBadge} ${styles.conflictBadgeInteractive}`}
                              title={worker.day_plan.conflicts.map((c) => `⚠️ ${c.message}`).join("\n")}
                              onClick={(e) => {
                                e.stopPropagation();
                                setAssignError(
                                  `Конфликты у ${worker.full_name}: ${worker.day_plan.conflicts.map((c) => c.message).join("; ")}`
                                );
                              }}
                            >
                              {worker.day_plan.conflicts.length} конфл.
                            </span>
                          )}
                        </span>
                        {isSelectedTaskWorker && (
                          <span className={styles.currentWorkerBadge}>Текущий</span>
                        )}
                        {!isSelectedTaskWorker && isEligible && selectedTaskId && (
                          <span className={styles.eligibleBadge}>✓ Подходит</span>
                        )}
                      </div>
                    </div>
                    <div className={styles.workerTimeline}>
                      {TIME_SLOTS.map((hour) => (
                        <div
                          key={hour}
                          className={styles.hourGridline}
                          style={{
                            left: `${((hour - TIMELINE_START_HOUR) / TOTAL_HOURS) * 100}%`,
                          }}
                        />
                      ))}

                      {/* Shift background */}
                      {worker.day_plan && (
                        <div
                          className={styles.shiftBackground}
                          style={{
                            left: `${timeToPercent(worker.day_plan.shift_start)}%`,
                            width: `${
                              timeToPercent(worker.day_plan.shift_end) -
                              timeToPercent(worker.day_plan.shift_start)
                            }%`,
                          }}
                        />
                      )}

                      {/* Route travel segments */}
                      {(worker.day_plan?.visits || []).map((visit, vIdx) => {
                        if (!visit.arrival) return null;
                        const arrPct = timeToPercent(visit.arrival);
                        const startPct = timeToPercent(visit.start);
                        if (startPct <= arrPct) return null;
                        const segWidth = Math.max(startPct - arrPct, 1.2);
                        return (
                          <div
                            key={`route-unassigned-${visit.ticket_id}-${vIdx}`}
                            className={styles.routeSegment}
                            style={{ left: `${arrPct}%`, width: `${segWidth}%` }}
                            title={`В пути к заявке #${visit.ticket_id} (${fmtTime(visit.arrival)} — ${fmtTime(visit.start)}${visit.waiting_minutes > 0 ? `, ожидание ${visit.waiting_minutes} мин` : ""})`}
                          >
                            <span className={styles.routeSegmentLabel}>🚗</span>
                          </div>
                        );
                      })}

                      {nowPercent !== null && (
                        <div className={styles.nowIndicator} style={{ left: `${nowPercent}%` }}>
                          <div className={styles.nowIndicatorDot} />
                        </div>
                      )}

                      {/* Tasks */}
                      {(worker.tickets || []).map((ticket) => {
                        const isMatchWorkType = isTaskVisible(ticket);
                        const left = timeToPercent(ticket.start);
                        const right = timeToPercent(ticket.end);
                        const width = Math.max(right - left, 3);
                        const isSelected = selectedTaskId === ticket.id;
                        const isLocked = lockedTaskIds.has(ticket.id);
                        const isDragging =
                          draggedTask && draggedTask.id === ticket.id;
                        const isConflicting = (worker.day_plan?.conflicts || []).some((c) =>
                          (c.ticket_ids || []).includes(ticket.id)
                        );

                        const statusCat = getStatusCategory(ticket);

                        return (
                          <div
                            key={ticket.id}
                            data-task-block
                            className={`${styles.taskBlock} ${getStatusClass(statusCat)} ${
                              isSelected ? styles.taskBlockSelected : ""
                            } ${isLocked ? styles.taskBlockLocked : ""} ${
                              isDragging ? styles.taskBlockDragging : ""
                            } ${!isMatchWorkType ? styles.taskBlockDimmedWorkType : ""} ${
                              isConflicting ? styles.taskBlockConflict : ""
                            }`}
                            style={{
                              left: `${left}%`,
                              width: `${width}%`,
                            }}
                            draggable={!isLocked && !isForeman}
                            onDragStart={(e) => handleDragStart(e, ticket, worker.id)}
                            onDragEnd={handleDragEnd}
                            onClick={(e) => handleTaskClick(e, ticket)}
                            onContextMenu={(e) =>
                              handleTaskContextMenu(e, ticket, worker.id)
                            }
                            onMouseEnter={(e) =>
                              handleTaskMouseEnter(e, ticket, worker)
                            }
                            onMouseLeave={handleTaskMouseLeave}
                            title={`#${ticket.id} ${ticket.title}${isConflicting ? " ⚠️ (Конфликт)" : ""}`}
                          >
                            {isLocked && <span className={styles.taskLockIcon}>🔒</span>}
                            <span className={styles.taskTitle}>
                              {width > 5 ? `#${ticket.id}` : ""}
                              {width > 10 ? ` ${ticket.title}` : ""}
                            </span>
                            {width > 8 && (
                              <span className={styles.taskTime}>
                                {fmtTime(ticket.start)}–{fmtTime(ticket.end)}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Redistribution Drop Zone ── */}
        {showRedistZone && (
          <div
            className={`${styles.redistZone} ${
              dragOverRedist ? styles.redistZoneActive : ""
            }`}
            onDragOver={handleDragOver}
            onDragEnter={handleRedistDragEnter}
            onDragLeave={handleRedistDragLeave}
            onDrop={handleRedistDrop}
          >
            <div className={styles.redistHeader}>
              <div className={styles.redistTitle}>
                📦 Зона перераспределения
                {combinedUnassignedTickets.length > 0 && (
                  <span className={styles.redistBadge}>
                    {combinedUnassignedTickets.length}
                  </span>
                )}
              </div>
              <span className={styles.redistSubtitle}>
                Перетащите сюда заявки для перераспределения
              </span>
            </div>
            <div className={styles.redistContent}>
              {combinedUnassignedTickets.length === 0 && (
                <div className={styles.redistEmpty}>
                  Нет заявок для перераспределения. Перетащите заявки сюда, чтобы снять назначение.
                </div>
              )}

              {combinedUnassignedTickets.map((ticket) => (
                <div
                  key={`unassigned-${ticket.id}`}
                  data-task-block
                  className={`${styles.redistTicket} ${selectedTaskId === ticket.id ? styles.taskBlockSelected : ""}`}
                  draggable={!isForeman}
                  onDragStart={(e) => {
                    const data = { ...ticket, sourceWorkerId: null };
                    draggedTaskRef.current = data;
                    setDraggedTask(data);
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData(
                      "text/plain",
                      JSON.stringify({ taskId: ticket.id, sourceWorkerId: null })
                    );
                  }}
                  onDragEnd={handleDragEnd}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedTaskId((prev) => (prev === ticket.id ? null : ticket.id));
                  }}
                >
                  <span className={styles.redistTicketId}>#{ticket.id}</span>
                  <i className={styles.dotPending} style={{ width: 7, height: 7, flexShrink: 0 }} />
                  <span>{ticket.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Context Menu ── */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className={styles.contextMenu}
          data-no-deselect
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className={styles.contextMenuItem}
            onClick={() => toggleLock(contextMenu.task.id, contextMenu.workerId)}
          >
            <span className={styles.contextMenuIcon}>
              {lockedTaskIds.has(contextMenu.task.id) ? "🔓" : "🔒"}
            </span>
            {lockedTaskIds.has(contextMenu.task.id) ? "Разблокировать" : "Заблокировать"}
          </button>
          <button
            className={`${styles.contextMenuItem} ${styles.contextMenuDanger}`}
            onClick={() => moveToRedist(contextMenu.task, contextMenu.workerId)}
          >
            <span className={styles.contextMenuIcon}>📦</span>
            На перераспределение
          </button>
        </div>
      )}

      {/* ── Tooltip ── */}
      {tooltip && (
        <div
          className={styles.taskTooltip}
          data-no-deselect
          style={{
            left: tooltip.x,
            top: tooltip.placeBelow ? tooltip.y : undefined,
            bottom: tooltip.placeBelow
              ? undefined
              : `${Math.max(10, window.innerHeight - tooltip.y)}px`,
          }}
          onMouseEnter={handleTooltipMouseEnter}
          onMouseLeave={handleTooltipMouseLeave}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <div className={styles.tooltipHeader}>
            <div className={styles.tooltipTitle} title={`#${tooltip.task.id} ${tooltip.task.title}`}>
              #{tooltip.task.id} {tooltip.task.title}
            </div>
            {lockedTaskIds.has(tooltip.task.id) && (
              <span className={styles.tooltipLockBadge}>🔒 Закреплена</span>
            )}
          </div>
          <div className={styles.tooltipRow}>
            <span className={styles.tooltipRowLabel}>Тип:</span>
            <span>{tooltip.task.work_type || "—"}</span>
          </div>
          <div className={styles.tooltipRow}>
            <span className={styles.tooltipRowLabel}>Время:</span>
            <span>
              {fmtTime(tooltip.task.start)} — {fmtTime(tooltip.task.end)}
            </span>
          </div>
          <div className={styles.tooltipRow}>
            <span className={styles.tooltipRowLabel}>Статус:</span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
              <i className={
                getStatusCategory(tooltip.task) === "in_progress" ? styles.dotInProgress :
                getStatusCategory(tooltip.task) === "completed" ? styles.dotCompleted :
                getStatusCategory(tooltip.task) === "cancelled" ? styles.dotCancelled :
                getStatusCategory(tooltip.task) === "route" ? styles.lineRoute : styles.dotPending
              } />
              {getStatusLabel(getStatusCategory(tooltip.task))}
            </span>
          </div>
          {tooltip.worker && (
            <div className={styles.tooltipRow}>
              <span className={styles.tooltipRowLabel}>Инженер:</span>
              <span>{tooltip.worker.full_name}</span>
            </div>
          )}
          <div className={styles.tooltipActions}>
            <button
              type="button"
              className={`${styles.tooltipBtn} ${styles.tooltipBtnLock}`}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                toggleLock(tooltip.task.id, tooltip.worker?.id);
              }}
            >
              {lockedTaskIds.has(tooltip.task.id) ? "🔓 Разлочить" : "🔒 Залочить"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
