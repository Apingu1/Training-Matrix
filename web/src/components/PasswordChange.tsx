import { useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../hooks/useAuth";

export default function PasswordChange() {
  const { me, logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!me?.must_change_password) return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword !== confirm) {
      setError("New password confirmation does not match");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      await logout().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Password change failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop required-modal">
      <form className="modal-card compact" onSubmit={submit}>
        <div className="modal-icon"><KeyRound size={24} /></div>
        <h2>Set your permanent password</h2>
        <p className="muted">Your temporary password must be changed before the system can be used.</p>
        <label>Current temporary password<input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required /></label>
        <label>New password<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required /></label>
        <label>Confirm new password<input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></label>
        <p className="form-hint">At least 8 characters, including one capital letter and one number.</p>
        {error && <div className="alert error">{error}</div>}
        <button className="button primary wide" disabled={busy}>{busy ? "Changing…" : "Change password"}</button>
      </form>
    </div>
  );
}
