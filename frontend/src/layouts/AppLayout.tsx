import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Library, CalendarDays, BarChart3, Activity, Download, Settings as SettingsIcon, LogOut, PlusCircle, BookOpen, PieChart, Clock, ScanSearch, Wand2, ChevronLeft, ChevronRight, FolderOpen } from "lucide-react";
import { NotificationBell } from "@/components/NotificationBell";
import { ServerStatusBadge } from "@/components/ServerStatusBadge";
import { TokenBanner } from "@/components/TokenBanner";
import { LogFooter } from "@/components/LogFooter";
import { GlobalProgressBar } from "@/components/GlobalProgressBar";
import { TaskCenter } from "@/components/TaskCenter";
import { useAuth } from "@/lib/auth";
import { SPRING_NAV } from "@/lib/motion";
import { APP_NAME, APP_INITIALS } from "@/lib/brand";

const NAV = [
  { to: "/library",    label: "Library",    icon: Library },
  { to: "/queue",      label: "Queue",      icon: CalendarDays },
  { to: "/create",     label: "Create",     icon: PlusCircle },
  { to: "/analytics",  label: "Analytics",  icon: BarChart3 },
  { to: "/statistics", label: "Statistics", icon: PieChart },
  { to: "/classification", label: "Classification", icon: ScanSearch },
  { to: "/scheduler",  label: "Scheduler",  icon: Clock },
  { to: "/pipeline",   label: "Pipeline",   icon: Activity },
  { to: "/downloads",  label: "Downloads",  icon: Download },
  { to: "/assets",     label: "Assets",     icon: FolderOpen },
  { to: "/settings",   label: "Settings",   icon: SettingsIcon },
  { to: "/design",     label: "Design",     icon: Wand2 },
  { to: "/docs",       label: "Docs",       icon: BookOpen },
];

const pageVariants = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] } },
  exit:    { opacity: 0, y: -6, transition: { duration: 0.15 } },
};

export function AppLayout() {
  const { signOut, session } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar-collapsed") === "true");

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });
  };

  return (
    <div className="flex h-screen">
      <GlobalProgressBar />

      {/* Sidebar */}
      <nav
        className={`${collapsed ? "w-14 px-1.5 py-3" : "w-56 p-3"} flex flex-col gap-0.5 shrink-0 transition-[width] duration-200 overflow-hidden`}
        style={{ background: "rgba(10,10,16,1)", borderRight: "1px solid rgba(255,255,255,0.05)" }}
      >
        <motion.div
          className={`flex items-center mb-5 pt-1 min-w-0 ${collapsed ? "justify-center px-0" : "px-2 justify-between"}`}
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className={`flex items-center gap-2 min-w-0 ${collapsed ? "" : "flex-1"}`}>
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shrink-0">
              <span className="text-white text-[10px] font-bold">{APP_INITIALS}</span>
            </div>
            {!collapsed && <h1 className="text-sm font-bold text-white tracking-tight truncate">{APP_NAME}</h1>}
          </div>
          {!collapsed && (
            <button
              onClick={toggleCollapsed}
              className="shrink-0 text-gray-500 hover:text-gray-300 transition-colors p-1 rounded hover:bg-gray-800"
              title="Collapse sidebar"
            >
              <ChevronLeft size={13} />
            </button>
          )}
        </motion.div>

        {collapsed && (
          <button
            onClick={toggleCollapsed}
            className="flex items-center justify-center py-1.5 mb-1 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
            title="Expand sidebar"
          >
            <ChevronRight size={13} />
          </button>
        )}

        {NAV.map(({ to, label, icon: Icon }, i) => (
          <motion.div
            key={to}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.22, delay: i * 0.025, ease: [0.22, 1, 0.36, 1] }}
          >
            <NavLink to={to} className="relative block rounded-lg">
              {({ isActive }) => (
                <div
                  title={collapsed ? label : undefined}
                  className={`relative flex items-center py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors ${
                    collapsed ? "justify-center px-0" : "gap-3 px-3"
                  } ${isActive ? "text-white" : "text-gray-400 hover:text-gray-200"}`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-lg"
                      style={{ background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.2)" }}
                      transition={SPRING_NAV}
                    />
                  )}
                  {!isActive && (
                    <div className="absolute inset-0 rounded-lg hover:bg-white/[0.04] transition-colors" />
                  )}
                  <Icon size={16} className="relative z-10 shrink-0" />
                  {!collapsed && <span className="relative z-10 whitespace-nowrap">{label}</span>}
                </div>
              )}
            </NavLink>
          </motion.div>
        ))}

        <div className="mt-auto pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          {!collapsed && (
            <div className="px-3 mb-1.5 text-[11px] text-gray-600 truncate">
              {session?.user.email}
            </div>
          )}
          <button
            onClick={signOut}
            title={collapsed ? "Sign out" : undefined}
            className={`flex items-center py-2 rounded-lg text-sm font-medium text-gray-400 hover:text-white hover:bg-gray-800/50 transition-colors w-full cursor-pointer ${
              collapsed ? "justify-center px-0" : "gap-3 px-3"
            }`}
          >
            <LogOut size={16} />
            {!collapsed && "Sign out"}
          </button>
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <TokenBanner />
        <div className="flex items-center justify-end gap-1 px-4 py-2 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", background: "rgba(10,10,16,0.9)", backdropFilter: "blur(8px)" }}>
          <ServerStatusBadge />
          <TaskCenter />
          <NotificationBell />
        </div>

        <AnimatePresence mode="wait" initial={false}>
          <motion.main
            key={location.pathname}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className="flex-1 overflow-auto p-6"
          >
            <Outlet />
          </motion.main>
        </AnimatePresence>

        <LogFooter />
      </div>
    </div>
  );
}
