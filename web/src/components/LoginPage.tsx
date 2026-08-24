import { useState, type FormEvent } from "react";
import { BookOpenCheck, LockKeyhole, ShieldCheck } from "lucide-react";
import { useAuth } from "../hooks/useAuth";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-brand-panel">
        <div className="brand-lockup large">
          <span className="brand-mark">E</span>
          <div><strong>Eaststone</strong><span>Training Matrix</span></div>
        </div>
        <div className="login-message">
          <p className="eyebrow light">CONTROLLED KNOWLEDGE</p>
          <h1>The right document.<br />The right version.<br />The right people.</h1>
          <p>Secure access to effective procedures, role-based curricula and attributable training records.</p>
        </div>
        <div className="login-assurances">
          <span><ShieldCheck size={18} /> Controlled revisions</span>
          <span><BookOpenCheck size={18} /> Training evidence</span>
          <span><LockKeyhole size={18} /> Append-only audit</span>
        </div>
      </section>
      <section className="login-form-panel">
        <form className="login-card" onSubmit={submit}>
          <div>
            <p className="eyebrow">AUTHORISED ACCESS</p>
            <h2>Welcome back</h2>
            <p className="muted">Sign in with your individual Eaststone account.</p>
          </div>
          <label>Username<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {error && <div className="alert error">{error}</div>}
          <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in securely"}</button>
          <p className="login-footnote">Use of this system is monitored and recorded in the audit trail.</p>
        </form>
      </section>
    </main>
  );
}
