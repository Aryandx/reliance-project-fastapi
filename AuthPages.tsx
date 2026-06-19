/**
 * AuthPages.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * DROP INTO:  src/auth/AuthPages.tsx   (or wherever your auth pages live)
 *
 * EXPORTS:
 *   LoginPage          — full MUI login page component
 *   useAuthStore       — Zustand store (user, tokens, login, logout, refresh)
 *   setupAxiosAuth     — call once at app startup to add auth headers + auto-refresh
 *
 * STEP 1 — Set your backend URL (line ~47):
 *   Replace  "http://localhost:8000"  with your actual backend URL
 *
 * STEP 2 — Wire up the router in your App.tsx:
 *   import { LoginPage, setupAxiosAuth, useAuthStore } from "./auth/AuthPages";
 *   import api from "@/utils/yourAxiosInstance";  ← your existing instance
 *
 *   // In App root component (before routes):
 *   useEffect(() => { setupAxiosAuth(api); }, []);
 *
 *   // In your router:
 *   <Route path="/login" element={<LoginPage />} />
 *
 * STEP 3 — Protect routes:
 *   const { user } = useAuthStore();
 *   if (!user) return <Navigate to="/login" />;
 *
 * STEP 4 — Remove useAuthStore here if your codebase already has one.
 *   Just keep  setupAxiosAuth  and  LoginPage.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState, useEffect } from "react";
import {
  Alert, Box, Button, Card, CardContent, Chip,
  CircularProgress, Divider, IconButton, InputAdornment,
  Stack, TextField, Typography,
} from "@mui/material";
import { Lock, Mail, Visibility, VisibilityOff, Work } from "@mui/icons-material";
import axios, { AxiosInstance } from "axios";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// ─── STEP 1: Set your backend base URL ───────────────────────────────────────
const API_BASE = "http://localhost:8000";
// e.g. const API_BASE = "https://your-api.onrender.com";
// ─────────────────────────────────────────────────────────────────────────────

const authApi = axios.create({ baseURL: API_BASE });

// ════════════════════════════════════════════════════════════════════════════
//  AUTH STORE  (Zustand — persisted to localStorage)
// ════════════════════════════════════════════════════════════════════════════

interface AuthUser {
  _id:        string;
  name:       string;
  email:      string;
  role:       string;
  employeeId: string;
}

interface AuthState {
  user:         AuthUser | null;
  accessToken:  string | null;
  refreshToken: string | null;

  setAuth:  (user: AuthUser, accessToken: string, refreshToken: string) => void;
  clearAuth: () => void;
  setAccessToken: (token: string) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user:         null,
      accessToken:  null,
      refreshToken: null,

      setAuth: (user, accessToken, refreshToken) =>
        set({ user, accessToken, refreshToken }),

      clearAuth: () =>
        set({ user: null, accessToken: null, refreshToken: null }),

      setAccessToken: (token) =>
        set({ accessToken: token }),
    }),
    {
      name: "ril-auth",  // localStorage key
      partialize: (s) => ({
        user:         s.user,
        accessToken:  s.accessToken,
        refreshToken: s.refreshToken,
      }),
    }
  )
);

// Convenience helpers (match the pattern the team's codebase uses)
export const getEmployeeRole  = () => useAuthStore.getState().user?.role  ?? "";
export const getEmployeeGroup = () => useAuthStore.getState().user?.employeeId ?? "";

// ════════════════════════════════════════════════════════════════════════════
//  AXIOS INTERCEPTOR SETUP
// ════════════════════════════════════════════════════════════════════════════

let _refreshPromise: Promise<string> | null = null;

/**
 * Call once in your App root:
 *   import { setupAxiosAuth } from "./auth/AuthPages";
 *   import api from "@/utils/yourAxiosInstance";
 *   useEffect(() => setupAxiosAuth(api), []);
 *
 * Or pass your team's shared axios instance here.
 * This adds:
 *   1. Authorization: Bearer <accessToken> header on every request
 *   2. Auto-refresh on 401 — retries the original request with the new token
 */
export function setupAxiosAuth(api: AxiosInstance) {
  // Add access token to every request
  api.interceptors.request.use((config) => {
    const token = useAuthStore.getState().accessToken;
    if (token) config.headers["Authorization"] = `Bearer ${token}`;
    return config;
  });

  // On 401 — try to refresh, retry once
  api.interceptors.response.use(
    (res) => res,
    async (error) => {
      const original = error.config;
      if (error.response?.status !== 401 || original._retried) {
        return Promise.reject(error);
      }
      original._retried = true;

      const refreshToken = useAuthStore.getState().refreshToken;
      if (!refreshToken) {
        useAuthStore.getState().clearAuth();
        window.location.href = "/login";
        return Promise.reject(error);
      }

      try {
        // Deduplicate concurrent refresh calls
        if (!_refreshPromise) {
          _refreshPromise = authApi
            .post("/api/auth/refresh", { refreshToken })
            .then((r) => {
              const { accessToken, refreshToken: newRefresh } = r.data;
              useAuthStore.getState().setAccessToken(accessToken);
              // Update refresh token in store
              useAuthStore.setState({ refreshToken: newRefresh });
              return accessToken;
            })
            .finally(() => { _refreshPromise = null; });
        }

        const newToken = await _refreshPromise;
        original.headers["Authorization"] = `Bearer ${newToken}`;
        return api(original);
      } catch {
        useAuthStore.getState().clearAuth();
        window.location.href = "/login";
        return Promise.reject(error);
      }
    }
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  ROLE COLOR MAP
// ════════════════════════════════════════════════════════════════════════════
const ROLE_COLORS: Record<string, "error" | "warning" | "info" | "success" | "default"> = {
  HR:         "error",
  Manager:    "warning",
  "Tech Lead": "info",
  Buddy:      "success",
  Intern:     "default",
};

// ════════════════════════════════════════════════════════════════════════════
//  LOGIN PAGE
// ════════════════════════════════════════════════════════════════════════════

interface LoginPageProps {
  /** Called after successful login — use for navigation.
   *  e.g. onSuccess={() => navigate("/dashboard")}
   *  If omitted, redirects to "/" by default.
   */
  onSuccess?: (user: AuthUser) => void;
}

export function LoginPage({ onSuccess }: LoginPageProps) {
  const { setAuth } = useAuthStore();

  const [email,       setEmail]       = useState("");
  const [password,    setPassword]    = useState("");
  const [showPass,    setShowPass]    = useState(false);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("Please enter both email and password.");
      return;
    }

    setLoading(true);
    try {
      const { data } = await authApi.post("/api/auth/login", {
        email:    email.trim().toLowerCase(),
        password,
      });

      setAuth(data.user, data.accessToken, data.refreshToken);

      if (onSuccess) {
        onSuccess(data.user);
      } else {
        window.location.href = "/";
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail ?? "Login failed. Please try again.";
      setError(Array.isArray(msg) ? msg.map((m: any) => m.msg).join(", ") : String(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight:       "100vh",
        display:         "flex",
        alignItems:      "center",
        justifyContent:  "center",
        background:      "linear-gradient(135deg, #0f1035 0%, #1a237e 50%, #0d47a1 100%)",
        p:               2,
      }}
    >
      <Card sx={{ width: "100%", maxWidth: 420, borderRadius: 3, boxShadow: 24 }}>
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          {/* Header */}
          <Stack alignItems="center" spacing={1.5} mb={3}>
            <Box
              sx={{
                width:  56, height: 56,
                borderRadius: "50%",
                background: "linear-gradient(135deg, #1a237e, #0d47a1)",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <Work sx={{ color: "white", fontSize: 28 }} />
            </Box>
            <Typography variant="h5" fontWeight={700} color="text.primary">
              Internship Portal
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Sign in to your account
            </Typography>
          </Stack>

          <Divider sx={{ mb: 3 }} />

          {/* Error alert */}
          {error && (
            <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {/* Form */}
          <Box component="form" onSubmit={handleLogin} noValidate>
            <Stack spacing={2.5}>
              <TextField
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                fullWidth
                required
                autoFocus
                autoComplete="email"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Mail fontSize="small" color="action" />
                    </InputAdornment>
                  ),
                }}
              />

              <TextField
                label="Password"
                type={showPass ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                fullWidth
                required
                autoComplete="current-password"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Lock fontSize="small" color="action" />
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton onClick={() => setShowPass((p) => !p)} edge="end" size="small">
                        {showPass ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />

              <Button
                type="submit"
                variant="contained"
                fullWidth
                size="large"
                disabled={loading}
                sx={{
                  mt: 1, py: 1.4, fontWeight: 600,
                  background: "linear-gradient(135deg, #1a237e, #0d47a1)",
                  "&:hover": { background: "linear-gradient(135deg, #0d1b6b, #0a3d8a)" },
                }}
              >
                {loading ? <CircularProgress size={22} color="inherit" /> : "Sign In"}
              </Button>
            </Stack>
          </Box>

          {/* Role reference */}
          <Box mt={3}>
            <Typography variant="caption" color="text.secondary" display="block" mb={1} textAlign="center">
              Access is role-based
            </Typography>
            <Stack direction="row" flexWrap="wrap" gap={0.5} justifyContent="center">
              {Object.keys(ROLE_COLORS).map((role) => (
                <Chip key={role} label={role} size="small" color={ROLE_COLORS[role]} variant="outlined" />
              ))}
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  REGISTER PAGE  (HR-only — embedded in HR dashboard or separate route)
// ════════════════════════════════════════════════════════════════════════════

interface RegisterPageProps {
  /** Pass your team's authed axios instance so it sends the HR token */
  api: AxiosInstance;
  onCreated?: (user: AuthUser) => void;
}

export function RegisterUserForm({ api: apiInstance, onCreated }: RegisterPageProps) {
  const [form, setForm] = useState({
    name: "", email: "", password: "", role: "Intern", employeeId: "",
  });
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const set = (field: string) => (e: React.ChangeEvent<HTMLInputElement | { value: unknown }>) =>
    setForm((f) => ({ ...f, [field]: (e.target as HTMLInputElement).value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); setSuccess(null);
    if (!form.name || !form.email || !form.password) {
      setError("Name, email, and password are required."); return;
    }
    setLoading(true);
    try {
      const { data } = await apiInstance.post("/api/auth/register", form);
      setSuccess(`Account created for ${data.user.name} (${data.user.role})`);
      setForm({ name: "", email: "", password: "", role: "Intern", employeeId: "" });
      onCreated?.(data.user);
    } catch (err: any) {
      const msg = err.response?.data?.detail ?? "Registration failed.";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack spacing={2}>
        {error   && <Alert severity="error"   onClose={() => setError(null)}>{error}</Alert>}
        {success && <Alert severity="success" onClose={() => setSuccess(null)}>{success}</Alert>}

        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField label="Full Name"  value={form.name}       onChange={set("name")}       fullWidth required />
          <TextField label="Employee ID" value={form.employeeId} onChange={set("employeeId")} fullWidth
            helperText="Auto-derived from email if left blank" />
        </Stack>

        <TextField label="Email" type="email" value={form.email} onChange={set("email")} fullWidth required />
        <TextField label="Temporary Password" type="password" value={form.password}
          onChange={set("password")} fullWidth required helperText="User should change this on first login" />

        <TextField
          select
          label="Role"
          value={form.role}
          onChange={set("role")}
          fullWidth
          SelectProps={{ native: true }}
        >
          {["Intern", "Buddy", "Tech Lead", "Manager", "HR"].map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </TextField>

        <Button
          type="submit"
          variant="contained"
          disabled={loading}
          sx={{ alignSelf: "flex-start", px: 4 }}
        >
          {loading ? <CircularProgress size={20} color="inherit" /> : "Create Account"}
        </Button>
      </Stack>
    </Box>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  CHANGE PASSWORD PAGE  (for any logged-in user)
// ════════════════════════════════════════════════════════════════════════════

interface ChangePasswordProps {
  api: AxiosInstance;
}

export function ChangePasswordForm({ api: apiInstance }: ChangePasswordProps) {
  const [form, setForm]     = useState({ currentPassword: "", newPassword: "", confirm: "" });
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const set = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); setSuccess(false);
    if (form.newPassword !== form.confirm) {
      setError("New passwords do not match."); return;
    }
    if (form.newPassword.length < 6) {
      setError("New password must be at least 6 characters."); return;
    }
    setLoading(true);
    try {
      await apiInstance.post("/api/auth/change-password", {
        currentPassword: form.currentPassword,
        newPassword:     form.newPassword,
      });
      setSuccess(true);
      setForm({ currentPassword: "", newPassword: "", confirm: "" });
    } catch (err: any) {
      setError(err.response?.data?.detail ?? "Failed to change password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate maxWidth={400}>
      <Stack spacing={2}>
        {error   && <Alert severity="error">{error}</Alert>}
        {success && <Alert severity="success">Password changed successfully.</Alert>}

        <TextField label="Current Password" type="password" value={form.currentPassword}
          onChange={set("currentPassword")} fullWidth required />
        <TextField label="New Password"     type="password" value={form.newPassword}
          onChange={set("newPassword")} fullWidth required />
        <TextField label="Confirm New Password" type="password" value={form.confirm}
          onChange={set("confirm")} fullWidth required />

        <Button type="submit" variant="contained" disabled={loading} sx={{ alignSelf: "flex-start" }}>
          {loading ? <CircularProgress size={20} color="inherit" /> : "Change Password"}
        </Button>
      </Stack>
    </Box>
  );
}
