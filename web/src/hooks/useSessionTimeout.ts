import { useEffect, useRef } from "react";
import { api } from "../api";
import type { Me } from "../types";

const LAST_ACTIVITY_KEY = "eaststone_training_matrix_last_activity";
const HEARTBEAT_INTERVAL_MS = 20_000;

export function useSessionTimeout(me: Me | null, logout: () => Promise<void>) {
  const logoutRef = useRef(logout);

  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  useEffect(() => {
    if (!me) {
      sessionStorage.removeItem(LAST_ACTIVITY_KEY);
      return;
    }

    let stopped = false;
    let idleTimer: number | null = null;
    let absoluteTimer: number | null = null;
    let lastHeartbeatAt = 0;
    const timeoutMs = Math.max(5, me.session_idle_minutes) * 60_000;
    const absoluteExpiry = new Date(me.session_expires_at).getTime();
    const stored = Number(sessionStorage.getItem(LAST_ACTIVITY_KEY));
    let lastActivityAt = Number.isFinite(stored) && stored > 0 ? stored : Date.now();
    sessionStorage.setItem(LAST_ACTIVITY_KEY, String(lastActivityAt));

    const clearTimers = () => {
      if (idleTimer !== null) window.clearTimeout(idleTimer);
      if (absoluteTimer !== null) window.clearTimeout(absoluteTimer);
      idleTimer = null;
      absoluteTimer = null;
    };

    const expire = (reason: "idle" | "absolute") => {
      if (stopped) return;
      stopped = true;
      clearTimers();
      sessionStorage.setItem(
        "eaststone_training_matrix_session_end_reason",
        reason === "idle"
          ? `Session ended after ${me.session_idle_minutes} minutes of inactivity.`
          : "Maximum session duration reached. Please sign in again.",
      );
      void logoutRef.current();
    };

    const scheduleIdle = () => {
      if (idleTimer !== null) window.clearTimeout(idleTimer);
      const elapsed = Date.now() - lastActivityAt;
      if (elapsed >= timeoutMs) {
        expire("idle");
        return;
      }
      idleTimer = window.setTimeout(() => expire("idle"), Math.max(250, timeoutMs - elapsed));
    };

    const scheduleAbsolute = () => {
      if (absoluteTimer !== null) window.clearTimeout(absoluteTimer);
      if (!Number.isFinite(absoluteExpiry)) return;
      const remaining = absoluteExpiry - Date.now();
      if (remaining <= 0) {
        expire("absolute");
        return;
      }
      absoluteTimer = window.setTimeout(() => expire("absolute"), Math.max(250, remaining));
    };

    const markHumanActivity = () => {
      if (stopped) return;
      const now = Date.now();
      if (now - lastActivityAt >= timeoutMs) {
        expire("idle");
        return;
      }
      if (Number.isFinite(absoluteExpiry) && now >= absoluteExpiry) {
        expire("absolute");
        return;
      }
      lastActivityAt = now;
      sessionStorage.setItem(LAST_ACTIVITY_KEY, String(now));
      scheduleIdle();
      if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeatAt = now;
        void api("/auth/activity", { method: "POST" }).catch(() => undefined);
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") markHumanActivity();
    };

    const activityEvents: Array<keyof WindowEventMap> = ["pointerdown", "keydown", "touchstart", "wheel"];
    activityEvents.forEach((eventName) => window.addEventListener(eventName, markHumanActivity, { passive: true }));
    window.addEventListener("focus", markHumanActivity);
    document.addEventListener("visibilitychange", onVisibilityChange);
    scheduleIdle();
    scheduleAbsolute();

    return () => {
      stopped = true;
      clearTimers();
      activityEvents.forEach((eventName) => window.removeEventListener(eventName, markHumanActivity));
      window.removeEventListener("focus", markHumanActivity);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [me]);
}
