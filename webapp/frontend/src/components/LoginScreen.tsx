import { useState } from "react";
import { login, signup } from "../api";

interface Props {
  onAuthed: (token: string, username: string) => void;
}

export default function LoginScreen({ onAuthed }: Props) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const call = mode === "login" ? login : signup;
    call(username, password)
      .then((r) => onAuthed(r.token, r.username))
      .catch((err) => setError(err?.response?.data?.detail || err.message || "Something went wrong"))
      .finally(() => setBusy(false));
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="brand"><span className="brand-mark" aria-hidden="true">D</span>DrawGen</div>
        <p className="hint">
          {mode === "login" ? "Log in to your diagrams." : "Create an account to start saving diagrams."}
        </p>
        <label className="field">
          <span>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
            required
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "signup" ? 8 : undefined}
            required
          />
        </label>
        {mode === "signup" && <p className="hint">At least 8 characters.</p>}
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "…" : mode === "login" ? "Log in" : "Sign up"}
        </button>
        <button
          type="button"
          className="link-btn"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Need an account? Sign up" : "Already have an account? Log in"}
        </button>
      </form>
    </div>
  );
}
