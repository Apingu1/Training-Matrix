import { useEffect, useState } from "react";
import {
  Archive,
  BookOpenCheck,
  ChevronLeft,
  ClipboardCheck,
  FileClock,
  FolderSearch,
  Files,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  UsersRound,
  X,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import PasswordChange from "./PasswordChange";

const nav = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/training", label: "My training", icon: BookOpenCheck, permission: "training.view_own" },
  { to: "/documents", label: "Controlled documents", icon: Files, permission: "documents.view" },
  { to: "/document-control", label: "Document control", icon: FileClock, any: ["documents.manage", "documents.review", "documents.approve"] },
  { to: "/source-discovery", label: "Source discovery", icon: FolderSearch, permission: "documents.manage" },
  { to: "/matrix", label: "Training matrix", icon: ClipboardCheck, permission: "training.view_team" },
  { to: "/people", label: "People & roles", icon: UsersRound, any: ["users.manage", "job_roles.manage"] },
  { to: "/security", label: "Permissions", icon: ShieldCheck, permission: "security_roles.manage" },
  { to: "/audit", label: "Audit trail", icon: Archive, permission: "audit.view" },
  { to: "/system", label: "System", icon: Settings, any: ["settings.manage", "backups.manage"] },
];

function sessionClock(date: Date): string {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = String(date.getDate()).padStart(2, "0");
  const month = months[date.getMonth()];
  const year = String(date.getFullYear()).slice(-2);
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${day} ${month} ${year} ${hour}:${minute}`;
}

export default function Layout() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("eaststone_training_matrix_sidebar_collapsed") === "true");
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const canSee = (item: (typeof nav)[number]) => {
    if (item.permission) return me?.permissions.includes(item.permission);
    if (item.any) return item.any.some((permission) => me?.permissions.includes(permission));
    return true;
  };

  const collapseSidebar = () => {
    setOpen(false);
    setCollapsed(true);
    localStorage.setItem("eaststone_training_matrix_sidebar_collapsed", "true");
  };

  const showSidebar = () => {
    setCollapsed(false);
    setOpen(true);
    localStorage.setItem("eaststone_training_matrix_sidebar_collapsed", "false");
  };

  const closeMobileSidebar = () => setOpen(false);

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${open ? "open" : ""} ${collapsed ? "collapsed" : ""}`}>
        <div className="sidebar-top">
          <div className="brand-lockup"><span className="brand-mark">E</span><div><strong>Eaststone</strong><span>Training Matrix</span></div></div>
          <button className="icon-button sidebar-close" onClick={collapseSidebar} aria-label="Collapse menu" title="Collapse menu"><X /></button>
        </div>
        <nav>
          <p className="nav-section">WORKSPACE</p>
          {nav.filter(canSee).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={closeMobileSidebar}>
              <Icon size={19} /><span>{label}</span><ChevronLeft className="nav-arrow" size={14} />
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-user">
          <div className="avatar">{me?.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</div>
          <div><strong>{me?.display_name}</strong><span>{me?.security_role.name}</span></div>
          <button className="icon-button" onClick={() => void logout()} title="Sign out"><LogOut size={18} /></button>
        </div>
      </aside>
      {open && !collapsed && <button className="sidebar-scrim" onClick={closeMobileSidebar} aria-label="Close menu" />}
      <div className="app-content">
        <header className="topbar">
          <button className="icon-button menu-button" onClick={showSidebar} aria-label="Open menu" title="Open menu"><Menu /></button>
          <div><span className="topbar-site">EASTSTONE</span><span className="topbar-divider" />Controlled Documents & Training</div>
          <div className="topbar-user" title="Session active"><span className="status-dot" /><span className="session-clock">{sessionClock(now)}</span></div>
        </header>
        <Outlet />
      </div>
      <PasswordChange />
    </div>
  );
}
