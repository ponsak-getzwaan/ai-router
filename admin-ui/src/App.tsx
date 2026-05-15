import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthCallback } from "./routes/AuthCallback";
import { ProtectedRoute } from "./routes/ProtectedRoute";
import { Health } from "./routes/Health";
import { Escalations } from "./routes/Escalations";
import { Bouncer } from "./routes/Bouncer";
import { Classifier } from "./routes/Classifier";
import { Strategist } from "./routes/Strategist";
import { RoutingRules } from "./routes/RoutingRules";
import { RoutingRuleEditor } from "./routes/RoutingRuleEditor";
import { Audit } from "./routes/Audit";
import { TestConsole } from "./routes/TestConsole";
import { Layout } from "./components/Layout";


const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30_000),
    },
  },
});

const router = createBrowserRouter([
  {
    path: "/auth/callback",
    element: <AuthCallback />,
  },
  {
    path: "/auth/error",
    element: (
      <div className="flex h-screen items-center justify-center">
        <p className="text-destructive">Authentication failed. Please try again.</p>
      </div>
    ),
  },
  {
    path: "/",
    element: <Navigate to="/admin/health" replace />,
  },
  {
    path: "/admin",
    element: (
      <ProtectedRoute>
        <Layout>
          <Navigate to="/admin/health" replace />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/health",
    element: (
      <ProtectedRoute>
        <Layout>
          <Health />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/escalations",
    element: (
      <ProtectedRoute>
        <Layout>
          <Escalations />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/bouncer",
    element: (
      <ProtectedRoute>
        <Layout>
          <Bouncer />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/classifier",
    element: (
      <ProtectedRoute>
        <Layout>
          <Classifier />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/strategist",
    element: (
      <ProtectedRoute>
        <Layout>
          <Strategist />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/routing-rules",
    element: (
      <ProtectedRoute>
        <Layout>
          <RoutingRules />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/routing-rules/:intent",
    element: (
      <ProtectedRoute>
        <Layout>
          <RoutingRuleEditor />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/audit",
    element: (
      <ProtectedRoute>
        <Layout>
          <Audit />
        </Layout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/test-console",
    element: (
      <ProtectedRoute>
        <Layout>
          <TestConsole />
        </Layout>
      </ProtectedRoute>
    ),
  },
]);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
