import { createContext, ReactNode, useContext, useMemo, useState } from "react";
import { api, clearSession, TokenResponse, UserRole } from "./client";

interface AuthState {
  username: string | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  /** Nach Erstanlage oder Einmal-Passwort: erst ein eigenes Passwort festlegen */
  mustChangePassword: boolean;
  /** honeypot: Inhalt des unsichtbaren Lockfelds (bei Menschen leer) */
  login: (username: string, password: string, honeypot?: string) => Promise<void>;
  /** Nach einer Passwortaenderung: das Backend schickt ein neues Token (alte Sitzungen sind beendet) */
  applyToken: (token: TokenResponse) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(localStorage.getItem("username"));
  const [role, setRole] = useState<UserRole | null>(localStorage.getItem("role") as UserRole | null);
  const [mustChangePassword, setMustChangePassword] = useState(localStorage.getItem("mustChangePassword") === "1");

  function applyToken(token: TokenResponse) {
    localStorage.setItem("token", token.access_token);
    localStorage.setItem("role", token.role);
    localStorage.setItem("username", token.username);
    if (token.must_change_password) {
      localStorage.setItem("mustChangePassword", "1");
    } else {
      localStorage.removeItem("mustChangePassword");
    }
    setUsername(token.username);
    setRole(token.role);
    setMustChangePassword(token.must_change_password);
  }

  async function login(usernameInput: string, password: string, honeypot = "") {
    const form = new URLSearchParams();
    form.set("username", usernameInput);
    form.set("password", password);
    form.set("email", honeypot);
    const response = await api.post<TokenResponse>("/auth/login", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    applyToken(response.data);
  }

  function logout() {
    clearSession();
    setUsername(null);
    setRole(null);
    setMustChangePassword(false);
  }

  const value = useMemo(
    () => ({ username, role, isAuthenticated: !!username, mustChangePassword, login, applyToken, logout }),
    [username, role, mustChangePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
