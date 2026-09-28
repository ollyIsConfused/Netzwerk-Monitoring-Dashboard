import { createContext, ReactNode, useContext, useMemo, useState } from "react";
import { api, UserRole } from "./client";

interface AuthState {
  username: string | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(localStorage.getItem("username"));
  const [role, setRole] = useState<UserRole | null>(localStorage.getItem("role") as UserRole | null);

  async function login(usernameInput: string, password: string) {
    const form = new URLSearchParams();
    form.set("username", usernameInput);
    form.set("password", password);
    const response = await api.post("/auth/login", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("token", response.data.access_token);
    localStorage.setItem("role", response.data.role);
    localStorage.setItem("username", response.data.username);
    setUsername(response.data.username);
    setRole(response.data.role);
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setUsername(null);
    setRole(null);
  }

  const value = useMemo(
    () => ({ username, role, isAuthenticated: !!username, login, logout }),
    [username, role],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
