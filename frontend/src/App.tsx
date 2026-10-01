import { Routes, Route, Navigate } from "react-router-dom";
import { Suspense, lazy, useEffect } from "react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { AppLayout } from "@/layouts/AppLayout";
import { LibraryPage } from "@/pages/Library";
import { QueuePage } from "@/pages/Queue";
import { AnalyticsPage } from "@/pages/Analytics";
import { PipelinePage } from "@/pages/Pipeline";
import { DownloadsPage } from "@/pages/Downloads";
import { AssetsPage } from "@/pages/Assets";
import { SettingsPage } from "@/pages/Settings";
import { PreviewPage } from "@/pages/Preview";
import { CreatePage } from "@/pages/Create";
import { DocsPage } from "@/pages/Docs";
import { StatisticsPage } from "@/pages/Statistics";
import { ClassificationPage } from "@/pages/Classification";
import { SchedulerPage } from "@/pages/Scheduler";
import { DesignPage } from "@/pages/Design";
import { LoginPage } from "@/pages/Login";
import { LandingPage } from "@/pages/Landing";
import { PrivacyPolicyPage } from "@/pages/PrivacyPolicy";
import { TermsPage } from "@/pages/Terms";
import { connectWs } from "@/lib/ws";
import { useWsInvalidation } from "@/hooks/useWsInvalidation";
import { useTaskTracker } from "@/hooks/useTaskTracker";
import { APP_INITIALS } from "@/lib/brand";

// Reel editor is code-split: @remotion/player + the timeline are ~400 kB and
// only ever needed on /editor/:mediaId.
const EditorPage = lazy(() =>
  import("@/pages/Editor").then((m) => ({ default: m.EditorPage })),
);

function ProtectedRoutes() {
  const { session, loading } = useAuth();

  useEffect(() => {
    if (session?.access_token) connectWs(session.access_token);
  }, [session]);

  // Central WS → cache invalidation (post_status, pipeline_*, edit_complete)
  useWsInvalidation();
  // Central WS → task store (all event types → Task Center)
  useTaskTracker();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center animate-pulse">
            <span className="text-white text-xs font-bold">{APP_INITIALS}</span>
          </div>
          <div className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-indigo-500 opacity-0 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s`, animationFillMode: "forwards" }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/queue" element={<QueuePage />} />
        <Route path="/create" element={<CreatePage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/pipeline" element={<PipelinePage />} />
        <Route path="/downloads" element={<DownloadsPage />} />
        <Route path="/audio" element={<Navigate to="/assets?type=music" replace />} />
        <Route path="/assets" element={<AssetsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/design" element={<DesignPage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/statistics" element={<StatisticsPage />} />
        <Route path="/classification" element={<ClassificationPage />} />
        <Route path="/scheduler" element={<SchedulerPage />} />
        <Route path="/preview/:id" element={<PreviewPage />} />
        <Route
          path="/editor/:mediaId"
          element={
            <Suspense
              fallback={
                <div className="min-h-[60vh] flex items-center justify-center text-gray-500 text-sm">
                  Loading editor…
                </div>
              }
            >
              <EditorPage />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/library" replace />} />
      </Route>
    </Routes>
  );
}

function LoginRoute() {
  const { session, loading } = useAuth();

  if (loading) return null;
  if (session) return <Navigate to="/library" replace />;

  return <LoginPage />;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public routes — no auth required */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />
        <Route path="/terms" element={<TermsPage />} />
        {/* Auth routes */}
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/*" element={<ProtectedRoutes />} />
      </Routes>
    </AuthProvider>
  );
}
