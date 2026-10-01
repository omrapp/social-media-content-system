import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { Toaster } from "sonner";
import { App } from "./App";
import { queryClient } from "@/lib/queryClient";
import { IS_DEMO, installDemoFetch } from "@/demo";
import { DemoBanner } from "@/demo/DemoBanner";
import "./index.css";

if (IS_DEMO) installDemoFetch();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* QueryClientProvider wraps outside BrowserRouter so cache survives navigation */}
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <App />
      </BrowserRouter>
      {IS_DEMO && <DemoBanner />}
      <Toaster
        richColors
        position="top-right"
        theme="dark"
        toastOptions={{ duration: 4000 }}
      />
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  </StrictMode>
);
