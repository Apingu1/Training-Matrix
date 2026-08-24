import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import LoginPage from "./components/LoginPage";
import { useAuth } from "./hooks/useAuth";
import AuditPage from "./pages/AuditPage";
import DashboardPage from "./pages/DashboardPage";
import DocumentControlPage from "./pages/DocumentControlPage";
import DocumentsPage from "./pages/DocumentsPage";
import MatrixPage from "./pages/MatrixPage";
import MyTrainingPage from "./pages/MyTrainingPage";
import PeoplePage from "./pages/PeoplePage";
import SecurityRolesPage from "./pages/SecurityRolesPage";
import SystemPage from "./pages/SystemPage";

function Gate({ permission, any, children }: { permission?: string; any?: string[]; children: React.ReactNode }) {
  const { me } = useAuth();
  const allowed = permission ? me?.permissions.includes(permission) : any?.some((item) => me?.permissions.includes(item));
  return allowed ? children : <Navigate to="/" replace />;
}

export default function App() {
  const { me, loading } = useAuth();
  if (loading) return <div className="loading-screen"><span className="spinner" /><p>Loading controlled workspace…</p></div>;
  if (!me) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="training" element={<Gate permission="training.view_own"><MyTrainingPage /></Gate>} />
        <Route path="documents" element={<Gate permission="documents.view"><DocumentsPage /></Gate>} />
        <Route path="document-control" element={<Gate any={["documents.manage", "documents.review", "documents.approve"]}><DocumentControlPage /></Gate>} />
        <Route path="matrix" element={<Gate permission="training.view_team"><MatrixPage /></Gate>} />
        <Route path="people" element={<Gate any={["users.manage", "job_roles.manage"]}><PeoplePage /></Gate>} />
        <Route path="security" element={<Gate permission="security_roles.manage"><SecurityRolesPage /></Gate>} />
        <Route path="audit" element={<Gate permission="audit.view"><AuditPage /></Gate>} />
        <Route path="system" element={<Gate any={["settings.manage", "backups.manage"]}><SystemPage /></Gate>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
