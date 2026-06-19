/**
 * TechLeadInternPages.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * DROP INTO:  src/workspace/pages/InternTracker/TechLeadInternPages.tsx
 *
 * THEN in PortalPages.ts (the barrel export file), add:
 *   export {
 *     TechLeadDashboardPage, TechLeadMapBuddyPage,
 *     TechLeadStandupFeedPage, TechLeadReviewInboxPage,
 *     InternDashboardPage, InternSubmitStandupPage,
 *     InternMyProgressPage, InternMyFeedbackPage,
 *   } from "./TechLeadInternPages";
 *
 * PLACEHOLDERS — search for every <INSERT ...> tag and replace:
 *   <INSERT YOUR TEAM'S AXIOS IMPORT PATH>   Line ~28
 *   <INSERT YOUR BACKEND BASE URL>            Line ~31
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState, useEffect, useCallback } from "react";
import {
  Alert, Avatar, Box, Button, Card, CardContent, Chip,
  CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, Divider, FormControl, Grid, InputLabel,
  LinearProgress, MenuItem, Paper, Select, Stack,
  Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, TextField, Tooltip, Typography,
} from "@mui/material";
import {
  AccountTree, ArrowForward, Assignment, AssignmentTurnedIn,
  CheckCircle, FeedOutlined, Feedback, Flag, Groups,
  RadioButtonUnchecked, RateReview, Refresh, Warning,
} from "@mui/icons-material";

// ─── STEP 1: Replace with your team's configured axios instance ──────────────
// Option A — if your team has a shared axios instance:
//   import api from "<INSERT YOUR TEAM'S AXIOS IMPORT PATH>";
//   e.g.  import api from "@/utils/axiosInstance";
//   e.g.  import { httpClient as api } from "@/services/api";
//
// Option B — keep this fallback and just set the base URL:
import axios from "axios";
const api = axios.create({
  baseURL: "http://localhost:8000/api/intern-tracker",
});
// NOTE: If your team's axios instance already sends auth headers (SSO token),
// use Option A and delete the lines above. Otherwise add your token here:
// api.interceptors.request.use(cfg => {
//   cfg.headers.Authorization = `Bearer <INSERT TOKEN GETTER>`;
//   return cfg;
// });
// ─────────────────────────────────────────────────────────────────────────────

import { getEmployeeRole, useAuthStore } from "@/store/AuthStore";

// ─── Types ────────────────────────────────────────────────────────────────────
interface InternProfile {
  _id: string;
  employeeId: string;
  name: string;
  email: string;
  employeeCode?: string;
  department?: string;
  startDate?: string;
  endDate?: string;
  status?: string;
}

interface AssignmentDoc {
  managerId?:  { _id: string; name: string; email: string };
  techLeadId?: { _id: string; name: string; email: string };
  buddyId?:    { _id: string; name: string; email: string };
  state?: string;
}

interface Standup {
  _id: string;
  internId?: InternProfile | string;
  buddyId?:  { name: string };
  date: string;
  yesterday: string;
  today: string;
  blockers?: string;
  slaStatus?: string;
  submittedAt?: string;
  reply?: { text: string; repliedAt: string };
}

interface Milestone {
  _id: string;
  title: string;
  description?: string;
  dueDate?: string;
  status: "PENDING" | "IN_PROGRESS" | "COMPLETED";
}

interface Review {
  _id: string;
  internId?: InternProfile | string;
  authorBuddyId?: { name: string };
  state: string;
  cycle?: string;
  publishedAt?: string;
  draft?: { strengths?: string; improvements?: string; rating?: number; summary?: string };
}

interface BuddyUser { _id: string; name: string; email: string; }

// ─── Shared helpers ───────────────────────────────────────────────────────────
const statusColor: Record<string, "success"|"warning"|"error"|"default"|"info"> = {
  ACTIVE: "success", COMPLETED: "info", ONBOARDING: "warning", TERMINATED: "error",
  MET: "success", PENDING: "warning", BREACHED: "error", BREACHED_OPEN: "error",
  PUBLISHED: "success", TL_REVIEW: "warning", MGR_REVIEW: "info", DRAFT: "default",
};

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <Typography variant="h6" fontWeight={700} gutterBottom sx={{ mt: 1 }}>{children}</Typography>
);

const StatCard = ({ icon, label, value, color = "primary.main" }:
  { icon: React.ReactNode; label: string; value: string | number; color?: string }) => (
  <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 2 }}>
    <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
      <Box sx={{ color, display: "flex" }}>{icon}</Box>
      <Box>
        <Typography variant="h5" fontWeight={800}>{value}</Typography>
        <Typography variant="body2" color="text.secondary">{label}</Typography>
      </Box>
    </Box>
  </Card>
);

const Loader = () => (
  <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
    <CircularProgress />
  </Box>
);

const fmt = (d?: string) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";

// ══════════════════════════════════════════════════════════════════════════════
//  INTERN — Dashboard
// ══════════════════════════════════════════════════════════════════════════════
export function InternDashboardPage() {
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [data, setData]         = useState<{
    intern?: InternProfile;
    assignment?: AssignmentDoc;
    todayStandup?: Standup | null;
    compliance?: { submitted: number; workingDays: number; compliance: number };
  }>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileRes, todayRes, complianceRes] = await Promise.all([
        api.get("/intern/me"),
        api.get("/intern/standup/today"),
        api.get("/intern/compliance"),
      ]);
      setData({
        intern:       profileRes.data.intern,
        assignment:   profileRes.data.assignment,
        todayStandup: todayRes.data.standup,
        compliance:   complianceRes.data,
      });
    } catch (e: any) {
      setError(e?.response?.data?.error || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Loader />;
  if (error)   return <Alert severity="error">{error}</Alert>;

  const { intern, assignment, todayStandup, compliance } = data;

  return (
    <Box sx={{ maxWidth: 960, mx: "auto", p: { xs: 1, md: 2 } }}>
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 3 }}>
        <Avatar sx={{ width: 56, height: 56, bgcolor: "primary.main", fontSize: 24, fontWeight: 800 }}>
          {intern?.name?.charAt(0).toUpperCase()}
        </Avatar>
        <Box>
          <Typography variant="h5" fontWeight={800}>{intern?.name}</Typography>
          <Typography color="text.secondary" variant="body2">
            {intern?.employeeCode && `${intern.employeeCode} · `}{intern?.department}
          </Typography>
        </Box>
        <Box sx={{ ml: "auto" }}>
          <Chip label={intern?.status || "ONBOARDING"}
            color={statusColor[intern?.status || ""] || "default"} size="small" />
        </Box>
      </Box>

      {/* Today standup banner */}
      {!todayStandup ? (
        <Alert severity="warning" sx={{ mb: 3 }}
          action={<Button color="inherit" size="small" href="/workspace/standup/submit">Submit Now</Button>}>
          You haven't submitted today's standup yet.
        </Alert>
      ) : (
        <Alert severity="success" icon={<AssignmentTurnedIn />} sx={{ mb: 3 }}>
          Today's standup submitted at{" "}
          {todayStandup.submittedAt
            ? new Date(todayStandup.submittedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
            : "—"}
          {todayStandup.reply && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>Buddy replied: "{todayStandup.reply.text}"</Typography>
          )}
        </Alert>
      )}

      {/* Stats */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          <StatCard icon={<Assignment sx={{ fontSize: 32 }} />}
            label="Standups Submitted" value={compliance?.submitted ?? 0} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard icon={<Flag sx={{ fontSize: 32 }} />}
            label="Working Days" value={compliance?.workingDays ?? 0} color="text.secondary" />
        </Grid>
        <Grid item xs={12} md={6}>
          <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 2 }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>Standup Compliance</Typography>
            <Typography variant="h4" fontWeight={800} color={
              (compliance?.compliance ?? 0) >= 80 ? "success.main" :
              (compliance?.compliance ?? 0) >= 60 ? "warning.main" : "error.main"
            }>{compliance?.compliance ?? 0}%</Typography>
            <LinearProgress variant="determinate" value={compliance?.compliance ?? 0}
              sx={{ mt: 1, height: 6, borderRadius: 3 }}
              color={(compliance?.compliance ?? 0) >= 80 ? "success" : (compliance?.compliance ?? 0) >= 60 ? "warning" : "error"} />
          </Card>
        </Grid>
      </Grid>

      {/* Team */}
      <SectionTitle>Your Team</SectionTitle>
      <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, mb: 3 }}>
        <CardContent>
          {[
            { role: "Manager",   person: assignment?.managerId },
            { role: "Tech Lead", person: assignment?.techLeadId },
            { role: "Buddy",     person: assignment?.buddyId },
          ].map(({ role, person }) => (
            <Box key={role} sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1.5 }}>
              <Typography sx={{ width: 80, fontWeight: 600, fontSize: 13 }} color="text.secondary">{role}</Typography>
              {person ? (
                <>
                  <Avatar sx={{ width: 28, height: 28, fontSize: 12 }}>{person.name.charAt(0)}</Avatar>
                  <Box>
                    <Typography variant="body2" fontWeight={600}>{person.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{person.email}</Typography>
                  </Box>
                </>
              ) : (
                <Chip label="Not assigned yet" size="small" color="warning" variant="outlined" />
              )}
            </Box>
          ))}
        </CardContent>
      </Card>

      <SectionTitle>Internship Period</SectionTitle>
      <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
        <CardContent sx={{ display: "flex", gap: 6 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Start Date</Typography>
            <Typography fontWeight={700}>{fmt(intern?.startDate)}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">End Date</Typography>
            <Typography fontWeight={700}>{fmt(intern?.endDate)}</Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  INTERN — Submit Standup
// ══════════════════════════════════════════════════════════════════════════════
export function InternSubmitStandupPage() {
  const [form, setForm]               = useState({ yesterday: "", today: "", blockers: "" });
  const [todayStandup, setTodayStandup] = useState<Standup | null>(null);
  const [loading, setLoading]         = useState(true);
  const [submitting, setSubmitting]   = useState(false);
  const [success, setSuccess]         = useState(false);
  const [error, setError]             = useState("");

  useEffect(() => {
    api.get("/intern/standup/today")
      .then((r) => { if (r.data.submitted) setTodayStandup(r.data.standup); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async () => {
    if (!form.yesterday.trim() || !form.today.trim()) {
      setError("'What I did yesterday' and 'What I'm doing today' are required.");
      return;
    }
    setSubmitting(true); setError("");
    try {
      await api.post("/intern/standup", form);
      setSuccess(true);
    } catch (e: any) {
      setError(e?.response?.data?.error || "Submission failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const todayLabel = new Date().toLocaleDateString("en-IN",
    { weekday: "long", year: "numeric", month: "long", day: "numeric" });

  if (loading) return <Loader />;

  return (
    <Box sx={{ maxWidth: 720, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <Assignment color="primary" sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight={800}>Daily Standup</Typography>
          <Typography variant="body2" color="text.secondary">{todayLabel}</Typography>
        </Box>
      </Box>

      {todayStandup && !success ? (
        <Alert severity="success" icon={<AssignmentTurnedIn />} sx={{ mb: 3 }}>
          You already submitted today's standup.
          {todayStandup.reply
            ? <Typography variant="body2" sx={{ mt: 0.5 }}>Buddy replied: "{todayStandup.reply.text}"</Typography>
            : <Typography variant="body2" sx={{ mt: 0.5 }} color="text.secondary">Waiting for buddy's reply…</Typography>}
        </Alert>
      ) : success ? (
        <Alert severity="success" sx={{ mb: 3 }}>Standup submitted! Your buddy will be notified.</Alert>
      ) : (
        <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
          <CardContent sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
            <TextField label="What did I do yesterday? *" multiline rows={3} fullWidth
              value={form.yesterday} disabled={submitting}
              onChange={(e) => setForm((f) => ({ ...f, yesterday: e.target.value }))}
              placeholder="Describe what you worked on yesterday…" />
            <TextField label="What will I do today? *" multiline rows={3} fullWidth
              value={form.today} disabled={submitting}
              onChange={(e) => setForm((f) => ({ ...f, today: e.target.value }))}
              placeholder="Describe your plan for today…" />
            <TextField label="Any blockers? (optional)" multiline rows={2} fullWidth
              value={form.blockers} disabled={submitting}
              onChange={(e) => setForm((f) => ({ ...f, blockers: e.target.value }))}
              placeholder="Any impediments or blockers? Leave blank if none." />
            <Button variant="contained" size="large" onClick={handleSubmit} disabled={submitting}
              startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : <AssignmentTurnedIn />}>
              {submitting ? "Submitting…" : "Submit Standup"}
            </Button>
          </CardContent>
        </Card>
      )}

      <Box sx={{ mt: 4 }}>
        <SectionTitle>Recent Standups</SectionTitle>
        <InternStandupHistory />
      </Box>
    </Box>
  );
}

function InternStandupHistory() {
  const [standups, setStandups] = useState<Standup[]>([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    api.get("/intern/standups", { params: { limit: 7 } })
      .then((r) => setStandups(r.data.standups))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LinearProgress />;
  if (!standups.length) return <Typography color="text.secondary" variant="body2">No standups yet.</Typography>;

  return (
    <Stack spacing={1.5}>
      {standups.map((s) => (
        <Card key={s._id} elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 2 }}>
          <Box sx={{ display: "flex", justifyContent: "space-between", mb: 1 }}>
            <Typography fontWeight={700} variant="body2">{fmt(s.date)}</Typography>
            <Chip label={s.slaStatus || "PENDING"} size="small"
              color={statusColor[s.slaStatus || ""] || "default"} />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
            <b>Yesterday:</b> {s.yesterday}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <b>Today:</b> {s.today}
          </Typography>
          {s.blockers && (
            <Typography variant="body2" color="warning.main" sx={{ mt: 0.5 }}>
              <b>Blocker:</b> {s.blockers}
            </Typography>
          )}
          {s.reply && (
            <Box sx={{ mt: 1, pl: 1.5, borderLeft: "3px solid", borderColor: "primary.main" }}>
              <Typography variant="caption" color="text.secondary">Buddy replied:</Typography>
              <Typography variant="body2">"{s.reply.text}"</Typography>
            </Box>
          )}
        </Card>
      ))}
    </Stack>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  INTERN — My Progress
// ══════════════════════════════════════════════════════════════════════════════
export function InternMyProgressPage() {
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [summary, setSummary]       = useState<{ total: number; completed: number; pending: number }>();
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState("");

  useEffect(() => {
    api.get("/intern/progress")
      .then((r) => { setMilestones(r.data.milestones); setSummary(r.data.summary); })
      .catch((e) => setError(e?.response?.data?.error || "Failed to load milestones"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loader />;
  if (error)   return <Alert severity="error">{error}</Alert>;

  const pct = summary && summary.total > 0
    ? Math.round((summary.completed / summary.total) * 100) : 0;

  return (
    <Box sx={{ maxWidth: 800, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <Flag color="primary" sx={{ fontSize: 32 }} />
        <Typography variant="h5" fontWeight={800}>My Progress</Typography>
      </Box>

      {summary && (
        <Card elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, mb: 3, p: 2 }}>
          <Box sx={{ display: "flex", justifyContent: "space-between", mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {summary.completed} of {summary.total} milestones completed
            </Typography>
            <Typography variant="body2" fontWeight={700} color="primary.main">{pct}%</Typography>
          </Box>
          <LinearProgress variant="determinate" value={pct}
            sx={{ height: 8, borderRadius: 4 }} color="success" />
        </Card>
      )}

      {milestones.length === 0
        ? <Alert severity="info">No milestones assigned yet.</Alert>
        : (
          <Stack spacing={1.5}>
            {milestones.map((m) => (
              <Card key={m._id} elevation={0}
                sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 2,
                  opacity: m.status === "COMPLETED" ? 0.75 : 1 }}>
                <Box sx={{ display: "flex", gap: 2, alignItems: "flex-start" }}>
                  <Box sx={{ pt: 0.25 }}>
                    {m.status === "COMPLETED"
                      ? <CheckCircle color="success" />
                      : m.status === "IN_PROGRESS"
                      ? <Flag color="warning" />
                      : <RadioButtonUnchecked color="disabled" />}
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography fontWeight={700}
                      sx={{ textDecoration: m.status === "COMPLETED" ? "line-through" : "none" }}>
                      {m.title}
                    </Typography>
                    {m.description && <Typography variant="body2" color="text.secondary">{m.description}</Typography>}
                    {m.dueDate && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                        Due: {fmt(m.dueDate)}
                      </Typography>
                    )}
                  </Box>
                  <Chip label={m.status.replace("_", " ")} size="small"
                    color={m.status === "COMPLETED" ? "success" : m.status === "IN_PROGRESS" ? "warning" : "default"} />
                </Box>
              </Card>
            ))}
          </Stack>
        )}
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  INTERN — My Feedback
// ══════════════════════════════════════════════════════════════════════════════
export function InternMyFeedbackPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");

  useEffect(() => {
    api.get("/intern/feedback")
      .then((r) => setReviews(r.data.reviews))
      .catch((e) => setError(e?.response?.data?.error || "Failed to load feedback"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loader />;
  if (error)   return <Alert severity="error">{error}</Alert>;

  return (
    <Box sx={{ maxWidth: 800, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <Feedback color="primary" sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight={800}>My Feedback</Typography>
          <Typography variant="body2" color="text.secondary">Published performance reviews from your buddy</Typography>
        </Box>
      </Box>

      {reviews.length === 0
        ? <Alert severity="info">No published reviews yet. They appear here after full approval.</Alert>
        : (
          <Stack spacing={2}>
            {reviews.map((r) => (
              <Card key={r._id} elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
                <CardContent>
                  <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
                    <Box>
                      <Typography fontWeight={700}>{r.cycle ? `Cycle: ${r.cycle}` : "Performance Review"}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Published {fmt(r.publishedAt)} · by{" "}
                        {typeof r.authorBuddyId === "object" ? r.authorBuddyId?.name : "Your Buddy"}
                      </Typography>
                    </Box>
                    {r.draft?.rating && (
                      <Typography fontWeight={800} color="warning.main">{r.draft.rating} / 5</Typography>
                    )}
                  </Box>
                  {r.draft?.strengths && (
                    <Box sx={{ mb: 1.5 }}>
                      <Typography variant="caption" fontWeight={700} color="success.main">STRENGTHS</Typography>
                      <Typography variant="body2">{r.draft.strengths}</Typography>
                    </Box>
                  )}
                  {r.draft?.improvements && (
                    <Box sx={{ mb: 1.5 }}>
                      <Typography variant="caption" fontWeight={700} color="warning.main">AREAS FOR IMPROVEMENT</Typography>
                      <Typography variant="body2">{r.draft.improvements}</Typography>
                    </Box>
                  )}
                  {r.draft?.summary && (
                    <Box sx={{ pt: 1.5, borderTop: "1px solid", borderColor: "divider" }}>
                      <Typography variant="caption" fontWeight={700} color="text.secondary">SUMMARY</Typography>
                      <Typography variant="body2">{r.draft.summary}</Typography>
                    </Box>
                  )}
                </CardContent>
              </Card>
            ))}
          </Stack>
        )}
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  TECH LEAD — Dashboard
// ══════════════════════════════════════════════════════════════════════════════
export function TechLeadDashboardPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [summary, setSummary] = useState<{
    totalInterns: number; todayStandups: number;
    pendingReviews: number; unassignedBuddy: number;
  }>();
  const [interns, setInterns] = useState<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, i] = await Promise.all([
        api.get("/tech-lead/dashboard-summary"),
        api.get("/tech-lead/interns"),
      ]);
      setSummary(s.data); setInterns(i.data.interns);
    } catch (e: any) {
      setError(e?.response?.data?.error || "Failed to load dashboard");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Loader />;
  if (error)   return <Alert severity="error">{error}</Alert>;

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Typography variant="h5" fontWeight={800} gutterBottom>Tech Lead Dashboard</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mb: 3 }}>
        {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
      </Typography>

      <Grid container spacing={2} sx={{ mb: 4 }}>
        {[
          { icon: <Groups sx={{ fontSize: 32 }} />,    label: "Total Interns",     value: summary?.totalInterns   ?? 0 },
          { icon: <Assignment sx={{ fontSize: 32 }} />, label: "Standups Today",   value: summary?.todayStandups  ?? 0, color: "success.main" },
          { icon: <RateReview sx={{ fontSize: 32 }} />, label: "Reviews Pending",  value: summary?.pendingReviews ?? 0, color: summary?.pendingReviews ? "warning.main" : undefined },
          { icon: <Warning sx={{ fontSize: 32 }} />,   label: "No Buddy Assigned", value: summary?.unassignedBuddy ?? 0, color: summary?.unassignedBuddy ? "error.main" : "success.main" },
        ].map((s) => (
          <Grid item xs={6} md={3} key={s.label}>
            <StatCard icon={s.icon} label={s.label} value={s.value} color={s.color} />
          </Grid>
        ))}
      </Grid>

      {(summary?.unassignedBuddy ?? 0) > 0 && (
        <Alert severity="warning" sx={{ mb: 3 }}
          action={<Button color="inherit" size="small" href="/workspace/intern/map-buddy">Assign Now</Button>}>
          {summary?.unassignedBuddy} intern(s) have no buddy — standups can't flow until assigned.
        </Alert>
      )}

      <SectionTitle>Your Interns</SectionTitle>
      <TableContainer component={Paper} elevation={0}
        sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflowX: "auto" }}>
        <Table size="small" sx={{ minWidth: 600 }}>
          <TableHead sx={{ bgcolor: "grey.50" }}>
            <TableRow>
              {["Name", "Department", "Status", "Buddy", "Start Date"].map((h) => (
                <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {interns.map((intern) => (
              <TableRow key={intern._id} hover>
                <TableCell>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                    <Avatar sx={{ width: 28, height: 28, fontSize: 12 }}>{intern.name?.charAt(0)}</Avatar>
                    <Box>
                      <Typography variant="body2" fontWeight={600}>{intern.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{intern.employeeCode}</Typography>
                    </Box>
                  </Box>
                </TableCell>
                <TableCell><Typography variant="body2">{intern.department || "—"}</Typography></TableCell>
                <TableCell>
                  <Chip label={intern.status || "—"} size="small"
                    color={statusColor[intern.status || ""] || "default"} />
                </TableCell>
                <TableCell>
                  {intern.buddy
                    ? <Typography variant="body2">{intern.buddy.name}</Typography>
                    : <Chip label="Unassigned" size="small" color="warning" variant="outlined" />}
                </TableCell>
                <TableCell><Typography variant="body2">{fmt(intern.startDate)}</Typography></TableCell>
              </TableRow>
            ))}
            {interns.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  No interns assigned to you yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  TECH LEAD — Map Buddy
// ══════════════════════════════════════════════════════════════════════════════
export function TechLeadMapBuddyPage() {
  const [interns, setInterns]     = useState<any[]>([]);
  const [buddies, setBuddies]     = useState<BuddyUser[]>([]);
  const [loading, setLoading]     = useState(true);
  const [saving, setSaving]       = useState<string | null>(null);
  const [error, setError]         = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  useEffect(() => {
    Promise.all([api.get("/tech-lead/interns"), api.get("/tech-lead/buddies")])
      .then(([ir, br]) => { setInterns(ir.data.interns); setBuddies(br.data.buddies); })
      .catch((e) => setError(e?.response?.data?.error || "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  const handleAssign = async (internId: string, buddyUserId: string) => {
    if (!buddyUserId) return;
    setSaving(internId); setError(""); setSuccessMsg("");
    try {
      await api.post("/tech-lead/assign-buddy", { internId, buddyUserId });
      setInterns((prev) =>
        prev.map((i) => i._id === internId
          ? { ...i, buddyAssigned: true, buddy: buddies.find((b) => b._id === buddyUserId) }
          : i)
      );
      setSuccessMsg("Buddy assigned successfully.");
    } catch (e: any) {
      setError(e?.response?.data?.error || "Assignment failed.");
    } finally { setSaving(null); }
  };

  if (loading) return <Loader />;

  return (
    <Box sx={{ maxWidth: 900, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <AccountTree color="primary" sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight={800}>Map Interns to Buddy</Typography>
          <Typography variant="body2" color="text.secondary">Assign a buddy to each of your interns</Typography>
        </Box>
      </Box>

      {error      && <Alert severity="error"   onClose={() => setError("")}      sx={{ mb: 2 }}>{error}</Alert>}
      {successMsg && <Alert severity="success" onClose={() => setSuccessMsg("")} sx={{ mb: 2 }}>{successMsg}</Alert>}

      {interns.length === 0
        ? <Alert severity="info">No interns are assigned to you yet.</Alert>
        : (
          <Stack spacing={2}>
            {interns.map((intern) => (
              <Card key={intern._id} elevation={0}
                sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
                <CardContent>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
                    <Avatar sx={{ bgcolor: "primary.main" }}>{intern.name?.charAt(0)}</Avatar>
                    <Box sx={{ flex: 1, minWidth: 120 }}>
                      <Typography fontWeight={700}>{intern.name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {intern.employeeCode} · {intern.department}
                      </Typography>
                    </Box>
                    <FormControl size="small" sx={{ minWidth: 220 }}>
                      <InputLabel>Select Buddy</InputLabel>
                      <Select label="Select Buddy" value={intern.buddy?._id || ""}
                        disabled={saving === intern._id}
                        onChange={(e) => handleAssign(intern._id, e.target.value)}>
                        <MenuItem value=""><em>— Unassigned —</em></MenuItem>
                        {buddies.map((b) => (
                          <MenuItem key={b._id} value={b._id}>
                            {b.name}
                            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>{b.email}</Typography>
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    {saving === intern._id
                      ? <CircularProgress size={20} />
                      : intern.buddyAssigned ? <CheckCircle color="success" /> : <Warning color="warning" />}
                  </Box>
                </CardContent>
              </Card>
            ))}
          </Stack>
        )}
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  TECH LEAD — Standup Feed
// ══════════════════════════════════════════════════════════════════════════════
export function TechLeadStandupFeedPage() {
  const [standups, setStandups]     = useState<Standup[]>([]);
  const [loading, setLoading]       = useState(true);
  const [dateFilter, setDateFilter] = useState("");
  const [error, setError]           = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (dateFilter) params.date = dateFilter;
      const r = await api.get("/tech-lead/standup-feed", { params });
      setStandups(r.data.standups);
    } catch (e: any) {
      setError(e?.response?.data?.error || "Failed to load standup feed");
    } finally { setLoading(false); }
  }, [dateFilter]);

  useEffect(() => { load(); }, [load]);

  return (
    <Box sx={{ maxWidth: 900, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <FeedOutlined color="primary" sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight={800}>Standup Feed</Typography>
          <Typography variant="body2" color="text.secondary">Daily updates from all your interns</Typography>
        </Box>
      </Box>

      <Box sx={{ display: "flex", gap: 2, mb: 3, flexWrap: "wrap", alignItems: "center" }}>
        <TextField type="date" size="small" label="Filter by date" value={dateFilter}
          onChange={(e) => setDateFilter(e.target.value)} InputLabelProps={{ shrink: true }}
          inputProps={{ max: new Date().toISOString().split("T")[0] }} sx={{ minWidth: 180 }} />
        {dateFilter && <Button size="small" onClick={() => setDateFilter("")} variant="outlined">Show All</Button>}
        <Button size="small" onClick={load} startIcon={<Refresh />} variant="outlined">Refresh</Button>
        <Typography variant="body2" color="text.secondary" sx={{ ml: "auto" }}>
          {standups.length} standup{standups.length !== 1 ? "s" : ""}
        </Typography>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {loading ? <Loader /> : standups.length === 0
        ? <Alert severity="info">{dateFilter ? `No standups on ${dateFilter}.` : "No standups yet."}</Alert>
        : (
          <Stack spacing={2}>
            {standups.map((s) => {
              const intern = typeof s.internId === "object" ? s.internId : null;
              return (
                <Card key={s._id} elevation={0}
                  sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
                  <CardContent>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 2 }}>
                      <Avatar sx={{ width: 32, height: 32, fontSize: 14 }}>{intern?.name?.charAt(0) || "?"}</Avatar>
                      <Box>
                        <Typography fontWeight={700} variant="body2">{intern?.name || "Unknown"}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {intern?.employeeCode} · {fmt(s.date)}
                        </Typography>
                      </Box>
                      <Box sx={{ ml: "auto", display: "flex", gap: 1 }}>
                        <Chip label={s.slaStatus || "PENDING"} size="small"
                          color={statusColor[s.slaStatus || ""] || "default"} />
                        {s.blockers && (
                          <Tooltip title={`Blocker: ${s.blockers}`}>
                            <Chip label="Blocker" size="small" color="warning" icon={<Warning />} />
                          </Tooltip>
                        )}
                      </Box>
                    </Box>
                    <Divider sx={{ mb: 1.5 }} />
                    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>
                      <Box>
                        <Typography variant="caption" fontWeight={700} color="text.secondary">YESTERDAY</Typography>
                        <Typography variant="body2">{s.yesterday}</Typography>
                      </Box>
                      <Box>
                        <Typography variant="caption" fontWeight={700} color="text.secondary">TODAY</Typography>
                        <Typography variant="body2">{s.today}</Typography>
                      </Box>
                    </Box>
                    {s.blockers && (
                      <Box sx={{ mt: 1.5, p: 1, bgcolor: "warning.50", borderRadius: 1,
                        border: "1px solid", borderColor: "warning.200" }}>
                        <Typography variant="caption" fontWeight={700} color="warning.main">BLOCKER</Typography>
                        <Typography variant="body2">{s.blockers}</Typography>
                      </Box>
                    )}
                    {s.reply && (
                      <Box sx={{ mt: 1.5, pl: 1.5, borderLeft: "3px solid", borderColor: "success.main" }}>
                        <Typography variant="caption" color="text.secondary">Buddy replied:</Typography>
                        <Typography variant="body2">"{s.reply.text}"</Typography>
                      </Box>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </Stack>
        )}
    </Box>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
//  TECH LEAD — Review Inbox
// ══════════════════════════════════════════════════════════════════════════════
export function TechLeadReviewInboxPage() {
  const [reviews, setReviews]           = useState<Review[]>([]);
  const [loading, setLoading]           = useState(true);
  const [forwarding, setForwarding]     = useState<string | null>(null);
  const [dialog, setDialog]             = useState<{ reviewId: string; internName: string } | null>(null);
  const [comment, setComment]           = useState("");
  const [error, setError]               = useState("");
  const [successMsg, setSuccessMsg]     = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api.get("/tech-lead/reviews")
      .then((r) => setReviews(r.data.reviews))
      .catch((e) => setError(e?.response?.data?.error || "Failed to load reviews"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleForward = async () => {
    if (!dialog) return;
    setForwarding(dialog.reviewId); setError(""); setSuccessMsg("");
    try {
      await api.post(`/tech-lead/reviews/${dialog.reviewId}/forward`, { comment });
      setSuccessMsg("Review forwarded to Manager.");
      setReviews((prev) => prev.filter((r) => r._id !== dialog.reviewId));
      setDialog(null); setComment("");
    } catch (e: any) {
      setError(e?.response?.data?.error || "Forward failed.");
    } finally { setForwarding(null); }
  };

  if (loading) return <Loader />;

  return (
    <Box sx={{ maxWidth: 900, mx: "auto", p: { xs: 1, md: 2 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 3 }}>
        <RateReview color="primary" sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight={800}>Review Inbox</Typography>
          <Typography variant="body2" color="text.secondary">Reviews awaiting your approval</Typography>
        </Box>
        <Button size="small" onClick={load} startIcon={<Refresh />} sx={{ ml: "auto" }} variant="outlined">
          Refresh
        </Button>
      </Box>

      {error      && <Alert severity="error"   onClose={() => setError("")}      sx={{ mb: 2 }}>{error}</Alert>}
      {successMsg && <Alert severity="success" onClose={() => setSuccessMsg("")} sx={{ mb: 2 }}>{successMsg}</Alert>}

      {reviews.length === 0
        ? <Alert severity="success" icon={<CheckCircle />}>No reviews pending. You're all caught up!</Alert>
        : (
          <Stack spacing={2}>
            {reviews.map((r) => {
              const intern = typeof r.internId === "object" ? r.internId : null;
              const buddy  = typeof r.authorBuddyId === "object" ? r.authorBuddyId : null;
              return (
                <Card key={r._id} elevation={0}
                  sx={{ border: "1px solid", borderColor: "warning.200", borderRadius: 2 }}>
                  <CardContent>
                    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", mb: 2 }}>
                      <Box>
                        <Typography fontWeight={700}>{intern?.name || "Unknown Intern"}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {intern?.employeeCode} · Written by {buddy?.name || "Buddy"}
                          {r.cycle ? ` · Cycle: ${r.cycle}` : ""}
                        </Typography>
                      </Box>
                      <Chip label="Awaiting TL Review" size="small" color="warning" />
                    </Box>
                    {r.draft?.rating   && <Typography variant="body2" sx={{ mb: 1 }}><b>Rating:</b> {r.draft.rating}/5</Typography>}
                    {r.draft?.strengths    && <Box sx={{ mb: 1 }}><Typography variant="caption" fontWeight={700} color="success.main">STRENGTHS</Typography><Typography variant="body2">{r.draft.strengths}</Typography></Box>}
                    {r.draft?.improvements && <Box sx={{ mb: 2 }}><Typography variant="caption" fontWeight={700} color="warning.main">IMPROVEMENTS</Typography><Typography variant="body2">{r.draft.improvements}</Typography></Box>}
                    <Button variant="contained" size="small"
                      endIcon={forwarding === r._id ? <CircularProgress size={14} color="inherit" /> : <ArrowForward />}
                      disabled={!!forwarding}
                      onClick={() => setDialog({ reviewId: r._id, internName: intern?.name || "Intern" })}>
                      Review & Forward to Manager
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
          </Stack>
        )}

      <Dialog open={!!dialog} onClose={() => setDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Forward Review — {dialog?.internName}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Add your comment before forwarding to the Manager.
          </Typography>
          <TextField label="Your comment (optional)" multiline rows={3} fullWidth
            value={comment} onChange={(e) => setComment(e.target.value)}
            placeholder="e.g. Aligns with my observations. Strong initiative shown." />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setDialog(null); setComment(""); }}>Cancel</Button>
          <Button variant="contained" onClick={handleForward} disabled={!!forwarding} endIcon={<ArrowForward />}>
            Forward to Manager
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
