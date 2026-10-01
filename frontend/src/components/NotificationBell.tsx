import { useState, useCallback, useRef, useEffect } from "react";
import { Bell, Check, CheckCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Notification } from "@/types/notifications";
import { NOTIFICATION_TYPE_COLORS } from "@/constants/colors";
import { slideDown } from "@/lib/motion";

export function NotificationBell() {
  const { data: notifications, refetch } = useApi<Notification[]>("/notifications?unread=false&limit=20");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const unreadCount = (notifications || []).filter((n) => !n.read).length;

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const markRead = useCallback(async (id: string) => {
    await api.put(`/notifications/${id}/read`);
    refetch();
  }, [refetch]);

  const markAllRead = useCallback(async () => {
    await api.put("/notifications/read-all");
    refetch();
  }, [refetch]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
      >
        <Bell size={18} />
        <AnimatePresence>
          {unreadCount > 0 && (
            <motion.span
              key="badge"
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0, opacity: 0 }}
              transition={{ type: "spring", stiffness: 500, damping: 25 }}
              className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 rounded-full text-[10px] font-bold flex items-center justify-center text-white"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </motion.span>
          )}
        </AnimatePresence>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            variants={slideDown}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="absolute right-0 top-full mt-2 w-80 bg-gray-900/95 backdrop-blur border border-gray-700/80 rounded-xl shadow-2xl shadow-black/40 z-50 overflow-hidden"
          >
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-800">
              <span className="text-sm font-semibold text-gray-200">Notifications</span>
              {unreadCount > 0 && (
                <button
                  onClick={markAllRead}
                  className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1 cursor-pointer transition-colors"
                >
                  <CheckCheck size={12} />
                  Mark all read
                </button>
              )}
            </div>
            <div className="max-h-80 overflow-y-auto">
              {(notifications || []).length === 0 && (
                <p className="text-sm text-gray-500 py-6 text-center">No notifications</p>
              )}
              {(notifications || []).map((n, i) => (
                <motion.div
                  key={n.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.03, duration: 0.18 }}
                  className={`px-3 py-2.5 border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors ${!n.read ? "bg-gray-800/25" : ""}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className={`text-sm font-medium ${NOTIFICATION_TYPE_COLORS[n.type] || "text-gray-300"}`}>
                        {n.title}
                      </p>
                      {n.message && <p className="text-xs text-gray-500 mt-0.5 truncate">{n.message}</p>}
                      <p className="text-[10px] text-gray-600 mt-1">
                        {new Date(n.created_at).toLocaleString()}
                      </p>
                    </div>
                    {!n.read && (
                      <button
                        onClick={() => markRead(n.id)}
                        className="p-1 hover:bg-gray-700 rounded text-gray-500 hover:text-gray-300 transition-colors cursor-pointer shrink-0"
                      >
                        <Check size={12} />
                      </button>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
