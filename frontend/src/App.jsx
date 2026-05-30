import { useState, useEffect, useRef, useCallback, createContext, useContext } from "react";
import translations, { n } from "./translations";

const LangContext = createContext();
export function useLang() { return useContext(LangContext); }

const API = import.meta.env.VITE_API_URL || "http://localhost:5002/api";
const BASE = import.meta.env.BASE_URL;

function authFetch(url, token, opts = {}) {
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  return fetch(url, { ...opts, headers });
}

const fmtDate = (d) => d ? new Date(d).toLocaleDateString('en-GB') : "—";
const fmtTime = (d) => d ? new Date(d).toLocaleString() : "—";
const daysUntil = (d) => Math.ceil((new Date(d) - new Date()) / 86400000);

function UserAvatar({ user, size = 36, className = "" }) {
  const [imgError, setImgError] = useState(false);
  const initials = `${user?.first_name?.[0] || ""}${user?.last_name?.[0] || ""}`;
  useEffect(() => { setImgError(false); }, [user?.profile_picture]);
  if (user?.profile_picture && !imgError) {
    return (
      <img
        src={`${API}/uploads/avatars/${user.profile_picture}`}
        alt={initials}
        className={`avatar-photo ${className}`}
        style={{ width: size, height: size }}
        onError={() => setImgError(true)}
      />
    );
  }
  return <div className={`avatar ${className}`} style={{ width: size, height: size }}>{initials}</div>;
}

export default function App() {
  const [lang, setLang] = useState(() => localStorage.getItem("lang") || "en");
  const t = translations[lang];
  const toggleLang = () => {
    const next = lang === "en" ? "ar" : "en";
    setLang(next);
    localStorage.setItem("lang", next);
  };

  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("user")); }
    catch { return null; }
  });
  const [view, setView] = useState("dashboard");

  const [courses, setCourses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [quizzesSummary, setQuizzesSummary] = useState([]);
  const [attendanceRisk, setAttendanceRisk] = useState(null);
  const [myAttendance, setMyAttendance] = useState([]);

  const [bellOpen, setBellOpen] = useState(false);
  const bellRef = useRef(null);

  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [typing, setTyping] = useState(false);
  const chatEnd = useRef(null);

  const isProf = user?.role === "professor";

  const profAnnouncements   = announcements.filter(a => !a.is_notification);
  const sysNotifications    = announcements.filter(a =>  a.is_notification);
  const unreadCount         = sysNotifications.filter(a => !a.is_read).length;

  const reload = async () => {
    if (!token) return;
    const [cRes, aRes, anRes, qzRes] = await Promise.all([
      authFetch(`${API}/courses`, token),
      authFetch(`${API}/assignments`, token),
      authFetch(`${API}/announcements`, token),
      authFetch(`${API}/quizzes`, token),
    ]);
    if (cRes.ok)  setCourses((await cRes.json()).courses || []);
    if (aRes.ok)  setAssignments((await aRes.json()).assignments || []);
    if (anRes.ok) setAnnouncements((await anRes.json()).announcements || []);
    if (qzRes.ok) setQuizzesSummary((await qzRes.json()).quizzes || []);

    if (!isProf) {
      const riskRes = await authFetch(`${API}/ai/attendance-risk`, token);
      const attRes  = await authFetch(`${API}/attendance/student`, token);
      if (riskRes.ok) setAttendanceRisk(await riskRes.json());
      if (attRes.ok)  setMyAttendance((await attRes.json()).attendance || []);
    }
  };

  useEffect(() => { if (token) reload(); }, [token]);

  // Refresh user object on mount so profile_picture is always fresh
  useEffect(() => {
    if (!token || !user) return;
    if (user.profile_picture !== undefined) return; // already has it
    authFetch(`${API}/auth/me`, token)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          const updated = { ...user, ...data };
          setUser(updated);
          localStorage.setItem("user", JSON.stringify(updated));
        }
      })
      .catch(() => {});
  }, [token]);

  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // close bell dropdown on outside click
  useEffect(() => {
    const handler = (e) => { if (bellRef.current && !bellRef.current.contains(e.target)) setBellOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const res = await fetch(`${API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: fd.get("email"), password: fd.get("password") }),
    });
    const data = await res.json();
    if (res.ok) {
      setToken(data.access_token);
      setUser(data.user);
      localStorage.setItem("token", data.access_token);
      localStorage.setItem("user", JSON.stringify(data.user));
    } else {
      alert(data.error || "Login failed");
    }
  };

  const logout = async () => {
    // clear chat history on backend before logging out
    // tried doing this with useEffect cleanup but it didn't work
    if (token) {
      try {
        await authFetch(`${API}/ai/clear-history`, token, { method: "POST" });
      } catch (_) {}
    }
    localStorage.clear();
    setToken(null); setUser(null);
    setCourses([]); setAssignments([]); setAnnouncements([]);
    setMessages([]);
    setShowLanding(true);
  };

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput("");
    setMessages(p => [...p, { role: "user", text: msg, time: new Date() }]);
    setTyping(true);
    try {
      const res = await authFetch(`${API}/ai/chat`, token, {
        method: "POST", body: JSON.stringify({ message: msg, lang }),
      });
      const data = await res.json();
      setMessages(p => [...p, { role: "ai", text: data.response || data.error, time: new Date(), resources: data.resources || [] }]);
    } catch {
      setMessages(p => [...p, { role: "ai", text: "Sorry, I couldn't process that.", time: new Date(), resources: [] }]);
    } finally { setTyping(false); }
  };

  const [showLanding, setShowLanding] = useState(!token);

  if (!token || !user) {
    if (showLanding) return (
      <LangContext.Provider value={{ lang, setLang, t, toggleLang }}>
        <LandingPage onEnter={() => setShowLanding(false)} />
      </LangContext.Provider>
    );
    return (
      <LangContext.Provider value={{ lang, setLang, t, toggleLang }}>
        <LoginPage onLogin={handleLogin} onBack={() => setShowLanding(true)} />
      </LangContext.Provider>
    );
  }

  return (
    <LangContext.Provider value={{ lang, setLang, t, toggleLang }}>
    <div className="layout" dir={lang === "ar" ? "rtl" : "ltr"}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={`${BASE}academia.svg`} alt="Academia" className="sidebar-logo" />
        </div>
        <div className="sidebar-user">
          <UserAvatar user={user} size={36} />
          <div className="user-info">
            <div className="user-name">{user.first_name} {user.last_name}</div>
            <div className="user-role">{isProf ? t.roles.professor : t.roles.student}</div>
          </div>
        </div>
        <nav className="sidebar-nav">
          {[
            { id: "dashboard",    icon: "📊", label: t.sidebar.dashboard   },
            { id: "courses",      icon: "📚", label: t.sidebar.courses      },
            { id: "assignments",  icon: "📝", label: t.sidebar.assignments  },
            { id: "attendance",   icon: "✅", label: t.sidebar.attendance   },
            { id: "forum",        icon: "💬", label: t.sidebar.forum        },
            { id: "announcements",icon: "📢", label: t.sidebar.announcements },
            { id: "resources",    icon: "📁", label: t.sidebar.resources     },
            ...(isProf ? [{ id: "analytics", icon: "📈", label: t.sidebar.analytics }] : []),
            ...(isProf ? [{ id: "grades", icon: "🎓", label: t.sidebar.grades }] : []),
            { id: "ai_insights",  icon: "🧠", label: t.sidebar.ai_insights   },
            { id: "profile", icon: "👤", label: t.sidebar.profile },
          ].map(({ id, icon, label }) => (
            <button key={id} className={`nav-btn ${view === id ? "active" : ""}`} onClick={() => setView(id)}>
              <span>{icon}</span> {label}
            </button>
          ))}
        </nav>
        <button className="logout-btn" onClick={logout}>{t.nav.logout}</button>
      </aside>

      <div className="main">
        <header className="topbar">
          <h1 className="page-title">{t.titles[view] || view}</h1>

          <div className="topbar-right">
            <button className="lang-toggle-btn" onClick={toggleLang} title={t.nav.lang}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/></svg>
            </button>

          {/* Bell notification button */}
          <div className="bell-wrap" ref={bellRef}>
            <button className="bell-btn" onClick={() => setBellOpen(o => !o)} title={t.notifications?.title || "Notifications"}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
              </svg>
              {unreadCount > 0 && (
                <span className="bell-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </button>

            {bellOpen && (
              <div className="bell-dropdown">
                <div className="bell-dropdown-header">
                  <span>{t.notifications?.title || "Notifications"}</span>
                  {unreadCount > 0 && (
                    <button className="bell-mark-read" onClick={() => {
                      authFetch(`${API}/announcements/mark-read`, token, { method: "POST" }).then(reload);
                      setBellOpen(false);
                    }}>{t.notifications?.markAllRead || "Mark all read"}</button>
                  )}
                </div>
                {sysNotifications.filter(a => !a.is_read).length === 0
                  ? <div className="bell-empty">{t.notifications?.allCaughtUp || "You're all caught up!"}</div>
                  : sysNotifications.filter(a => !a.is_read).slice(0, 6).map(a => (
                    <div key={a.announcement_id} className="bell-item" onClick={() => {
                      authFetch(`${API}/announcements/mark-read`, token, { method: "POST" }).then(reload);
                      setBellOpen(false);
                    }}>
                      <div className="bell-item-title">{a.title}</div>
                      <div className="bell-item-content">{a.content}</div>
                      <div className="bell-item-meta">{a.course_name || ""} · {fmtDate(a.created_at)}</div>
                    </div>
                  ))
                }
                <button className="bell-view-all" onClick={() => {
                  authFetch(`${API}/announcements/mark-read`, token, { method: "POST" }).then(reload);
                  setBellOpen(false);
                }}>{t.notifications?.markAllRead || "Mark all as read"} →</button>
              </div>
            )}
          </div>
          </div>{/* end topbar-right */}
        </header>

        <div className="content">
          {view === "dashboard"     && <Dashboard user={user} isProf={isProf} courses={courses} assignments={assignments} announcements={profAnnouncements} quizzesSummary={quizzesSummary} attendanceRisk={attendanceRisk} myAttendance={myAttendance} />}
          {view === "courses"       && <CoursesView isProf={isProf} courses={courses} token={token} reload={reload} />}
          {view === "assignments"   && <AssignmentsView isProf={isProf} courses={courses} assignments={assignments} token={token} reload={reload} />}
          {view === "attendance"    && <AttendanceView isProf={isProf} courses={courses} token={token} user={user} myAttendance={myAttendance} reload={reload} />}
          {view === "forum"         && <ForumView courses={courses} token={token} user={user} />}
          {view === "announcements" && <AnnouncementsView isProf={isProf} courses={courses} announcements={profAnnouncements} token={token} reload={reload} />}
          {view === "ai_insights"  && <AIInsightsView isProf={isProf} token={token} user={user} setChatInput={setChatInput} setChatOpen={setChatOpen} />}
          {view === "resources"    && <ResourcesView isProf={isProf} courses={courses} token={token} reload={reload} />}
          {view === "analytics"    && isProf && <AnalyticsView isProf={isProf} token={token} user={user} courses={courses} />}
          {view === "grades"       && isProf && <GradesView courses={courses} token={token} />}
          {view === "profile"      && <ProfileView token={token} user={user} isProf={isProf} courses={courses} onUserUpdate={updatedUser => { setUser(updatedUser); localStorage.setItem("user", JSON.stringify(updatedUser)); }} />}
        </div>
      </div>

      <div className="chatbot-wrap">
        {!chatOpen && (
          <button className="chat-fab" onClick={() => setChatOpen(true)} title="AI Assistant">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="22" height="22">
              <path d="M12 2C6.477 2 2 6.155 2 11.25c0 2.278.87 4.36 2.303 5.963L3 21l4.565-1.31A10.68 10.68 0 0012 20.5c5.523 0 10-4.155 10-9.25S17.523 2 12 2z" fill="currentColor"/>
              <path d="M8 11.25h8M8 7.75h5" stroke="white" strokeWidth="1.6" strokeLinecap="round"/>
            </svg>
          </button>
        )}
        {chatOpen && (
          <div className="chat-window">
            <div className="chat-head">
              <div>
                <div className="chat-title">{t.ai.chatTitle}</div>
                <div className="chat-sub">{t.ai.placeholder}</div>
              </div>
              <button className="chat-close" onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <div className="chat-body">
              {messages.length === 0 && (
                <div className="chat-welcome">
                  <p>{t.ai.welcomeGreeting(user.first_name)}</p>
                  <p>{t.ai.welcomeHint}</p>
                  <div className="chat-suggestions">
                    {(isProf ? t.ai.profSuggestions : t.ai.studentSuggestions).map(s => (
                      <button key={s} className="suggestion-btn" onClick={() => { setChatInput(s); }}>{s}</button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  <div className="msg-bubble">{m.text}</div>
                  {m.role === "ai" && m.resources && m.resources.length > 0 && (
                    <div style={{marginTop:"0.5rem",padding:"0.6rem 0.8rem",background:"#f0f7ff",borderRadius:"8px",border:"1px solid #bfdbfe"}}>
                      <p style={{margin:"0 0 0.4rem",fontSize:"0.8rem",fontWeight:600,color:"#1d4ed8"}}>{t.ai.relatedResources}</p>
                      {m.resources.map(r => (
                        <div key={r.resource_id} style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0.3rem 0",borderBottom:"1px solid #dbeafe",gap:"0.5rem"}}>
                          <span style={{fontSize:"0.82rem",color:"#1e3a5f",fontWeight:500}}>
                            {r.title}
                            <span style={{color:"#6b7280",fontWeight:400,marginLeft:"0.3rem"}}>({r.course_name})</span>
                          </span>
                          <button className="btn-secondary" style={{padding:"0.2rem 0.6rem",fontSize:"0.75rem",flexShrink:0}}
                            onClick={() => authFetch(`${API}/resources/${r.resource_id}/download`, token).then(res => {
                              if (res.ok) res.blob().then(blob => {
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement("a"); a.href = url; a.download = r.title; a.click(); URL.revokeObjectURL(url);
                              });
                            })}>
                            {t.ai.download}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="msg-time">{fmtTime(m.time)}</div>
                </div>
              ))}
              {typing && <div className="msg ai"><div className="msg-bubble typing"><span/><span/><span/></div></div>}
              <div ref={chatEnd} />
            </div>
            <div className="chat-foot">
              <textarea className="chat-input" rows={2} placeholder={t.ai.placeholder}
                value={chatInput} onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
              />
              <button className="chat-send" onClick={sendChat} disabled={!chatInput.trim()}>{t.ai.send}</button>
            </div>
          </div>
        )}
      </div>
    </div>
    </LangContext.Provider>
  );
}

const BLOG_POSTS = [
  {
    id: 1,
    category: "AI & Performance",
    title: "AI-Powered Advising: What It Means for University Students",
    excerpt: "How a personalized AI report changes the way students understand their own academic standing — before it's too late.",
    image: "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=700&q=80",
    gradient: "linear-gradient(135deg, rgba(13,27,64,.7) 0%, rgba(30,58,120,.5) 100%)",
    readTime: "4 min read",
    content: `For years, getting meaningful feedback on your academic performance meant waiting for a professor's office hours or hoping someone noticed you were falling behind. Academia changes that with an AI advisor built directly into the platform.

Every student has access to a personalized academic report generated from live data — their actual attendance records, submission history, graded assignments, and upcoming deadlines. The report is written as if an advisor is talking directly to you: not a dry list of statistics, but paragraphs that highlight what you're doing well, where you need to focus, and exactly which assignments to tackle first this week.

The AI reads your data the way a good advisor would. If your attendance in one course is trending toward the 75% threshold, it tells you — by name, with the specific percentage — before you hit the point of no return. If you have three assignments due in the same week, it ranks them by urgency and point value and tells you which one to open first and why.

For professors, the AI generates a class briefing: which students are at risk, what the overall attendance and submission picture looks like, and concrete actions to take this week. "Reach out to Mohamed — he's missed 4 of 15 classes in Systems Analysis" is the kind of specific, actionable output that makes early intervention possible.

This isn't a generic chatbot. It's a context-aware advisor trained on your live platform data, updated in real time, and designed to give you the kind of guidance that actually changes behavior.`
  },
  {
    id: 2,
    category: "Attendance",
    title: "The 75% Rule: Why Attendance Tracking Saves Academic Careers",
    excerpt: "Most students know the number. What's harder to feel, until it's too late, is how quickly absences compound across a semester.",
    image: "https://images.unsplash.com/photo-1541178735493-479c1a27ed24?w=700&q=80",
    gradient: "linear-gradient(135deg, rgba(15,42,90,.75) 0%, rgba(26,74,110,.6) 100%)",
    readTime: "3 min read",
    content: `Most students know the number abstractly: you need to attend 75% of your classes to pass. What's harder to feel, until it's too late, is how quickly absences compound.

In a course with 15 sessions, you can afford to miss 3. By the fourth absence, you're at 73.3% — below the threshold. If you've been splitting that course across a semester with late arrivals and skipped sessions, you might not even realize you've crossed the line until the end of term.

Academia tracks attendance session-by-session and calculates your running rate per course automatically. The dashboard shows your current attendance percentage the moment you log in. But more importantly, the platform flags courses where you're approaching the threshold — not after you've failed, but while you still have time to fix it.

The AI advisor takes this further. If your attendance in a course is at 78% and you have 5 sessions left in the semester, it calculates how many sessions you can still miss while staying above 75%. That's the difference between abstract data and actionable guidance.

For professors, the analytics view surfaces every student whose attendance has dropped below 75% — by name, by course, with the exact count of absences. Early contact from a professor at 76% is far more effective than a warning letter at 65%. The data is there. The platform makes sure it gets used.`
  },
  {
    id: 3,
    category: "Workload Management",
    title: "Managing 6 Courses at Once: How Smart Deadline Management Works",
    excerpt: "Six courses, six deadlines, one priority list. How the platform turns deadline chaos into a clear action plan.",
    image: "https://images.unsplash.com/photo-1484480974693-6ca0a78fb36b?w=700&q=80",
    gradient: "linear-gradient(135deg, rgba(18,34,62,.75) 0%, rgba(36,61,110,.6) 100%)",
    readTime: "3 min read",
    content: `Six courses. Six sets of deadlines, submission portals, and grading rubrics. For a full-time student, keeping track of what's due, what's graded, and what's been forgotten is a real cognitive load.

The assignments view on Academia brings everything into a single timeline. Every assignment across every enrolled course appears in one list, ordered by due date, with your submission status clearly marked: pending, submitted, or graded with your score. Overdue assignments that were never submitted are automatically closed and graded 0 — no ambiguity, no chasing down whether something was received.

The real feature for workload management is the AI priority list. When you generate your academic report, the AI doesn't just list your pending assignments — it ranks them. An assignment due in 2 days and worth 25 points comes before one due in 10 days and worth 10 points. The AI writes it as direct advice: "I'd start with the Systems Analysis report — it's your most urgent item and carries significant weight."

The workload indicator at the top of the priority list gives you an at-a-glance read: light, moderate, or heavy. If three assignments are due in the same five-day window, the AI flags it as a crunch period and adjusts its recommendations accordingly.

The goal isn't to eliminate the work — it's to make sure you always know what to do next.`
  }
];

function LandingPage({ onEnter }) {
  const { t, lang, toggleLang } = useContext(LangContext);
  const [blogPost, setBlogPost] = useState(null);
  const [mailSent, setMailSent]  = useState(false);

  const features = t.landing.features.map((f, i) => ({
    icon: [
      <svg key={0} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M8 2v4M16 2v4"/><path d="M8 14l2.5 2.5L16 11"/></svg>,
      <svg key={1} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4"/></svg>,
      <svg key={2} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l1.8 5.5H19l-4.6 3.4 1.7 5.5L12 13l-4.1 3.4 1.7-5.5L5 7.5h5.2z"/><path d="M12 17v5M8 21h8"/></svg>,
      <svg key={3} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>,
      <svg key={4} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>,
      <svg key={5} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M9 7h6M9 11h4"/></svg>,
    ][i],
    title: f.title,
    desc: f.desc,
  }));

  const steps = t.landing.steps;
  const profSteps = t.landing.profSteps;

  const lp = t.landing;

  return (
    <div className="landing" dir={lang === "ar" ? "rtl" : "ltr"}>

      {/* Navbar */}
      <nav className="landing-nav">
        <div className="landing-nav-brand">
          <img src={`${BASE}academia.svg`} alt="Academia" style={{height:'50px',width:'auto'}} />
        </div>
        <div className="landing-nav-right">
          <button className="lang-toggle-btn" onClick={toggleLang} title={t.nav.lang}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/></svg>
          </button>
          <button className="landing-nav-login" onClick={onEnter}>{t.nav.login}</button>
        </div>
      </nav>

      {/* Hero — campus photo background */}
      <section className="landing-hero">
        <div className="landing-hero-overlay" />
        <div className="landing-hero-inner">
          <div className="landing-eyebrow">{lp.eyebrow}</div>
          <h1 className="landing-title">{lp.heroTitle[0]}<br />{lp.heroTitle[1]}</h1>
          <p className="landing-subtitle">{lp.heroSubtitle}</p>
          <div className="landing-cta-row">
            <a className="landing-cta-primary" href="#how-it-works">{lp.exploreCta}</a>
            <a className="landing-cta-ghost" href="#for-professors">{lp.forProfCta}</a>
          </div>
        </div>

        <div className="landing-hero-visual">
          <div className="mockup-card mockup-main">
            <div className="mockup-topbar">
              <div className="mockup-dot" /><div className="mockup-dot" /><div className="mockup-dot" />
            </div>
            <div className="mockup-label">Attendance Rate</div>
            <div className="mockup-big-num">88%</div>
            <div className="mockup-bar-row">
              {[100,100,60,100,80,100,0,100,60,100].map((h,i) => (
                <div key={i} className="mockup-bar" style={{height: `${Math.max(h*0.32,4)}px`, opacity: h>0 ? 1 : 0.2}} />
              ))}
            </div>
            <div className="mockup-sub">Systems Analysis · 13 of 15 sessions attended</div>
          </div>
          <div className="mockup-card mockup-small mockup-float-1">
            <div className="mockup-label">{lp.nextDeadline}</div>
            <div className="mockup-small-title">Systems Analysis Report</div>
            <div className="mockup-tag">{lp.daysLeft}</div>
          </div>
          <div className="mockup-card mockup-small mockup-float-2">
            <div className="mockup-label">{lp.aiInsight}</div>
            <div className="mockup-small-title">Attendance risk in Database Systems — act now</div>
            <div className="mockup-tag mockup-tag-warn">{lp.approaching}</div>
          </div>
        </div>
      </section>

      {/* How it works — bis-fmi photo background */}
      <section className="landing-how" id="how-it-works">
        <div className="landing-how-overlay" />
        <div className="landing-how-inner">
          <div className="landing-section-label">{lp.howLabel}</div>
          <h2 className="landing-section-title">{lp.howTitle}</h2>
          <div className="landing-steps">
            {steps.map((s, i) => (
              <div key={i} className="landing-step">
                <div className="step-number">{String(i+1).padStart(2,"0")}</div>
                <h3 className="step-title">{s.title}</h3>
                <p className="step-desc">{s.desc}</p>
                {i < steps.length - 1 && <div className="step-connector" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing-features" id="features">
        <div className="landing-features-inner">
          <div className="landing-section-label">{lp.featuresLabel}</div>
          <h2 className="landing-section-title">{lp.featuresTitle}</h2>
          <div className="landing-features-grid">
            {features.map(f => (
              <div key={f.title} className="landing-feature-card">
                <div className="landing-feature-svg-icon">{f.icon}</div>
                <h3 className="landing-feature-title">{f.title}</h3>
                <p className="landing-feature-desc">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* For Professors */}
      <section className="landing-prof" id="for-professors">
        <div className="landing-prof-content">
          <div className="landing-section-label" style={{color:"#93b4d9"}}>{lp.profLabel}</div>
          <h2 className="landing-section-title" style={{color:"#fff", maxWidth:"420px"}}>{lp.profTitle}</h2>
          <div className="landing-prof-steps">
            {profSteps.map((s, i) => (
              <div key={i} className="prof-step">
                <div className="prof-step-num">{String(i+1).padStart(2,"0")}</div>
                <div>
                  <h3 className="prof-step-title">{s.title}</h3>
                  <p className="prof-step-desc">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="landing-prof-img">
          <img src="https://images.unsplash.com/photo-1580582932707-520aed937b7b?w=900&q=80" alt="University campus" />
        </div>
      </section>

      {/* From the Founders */}
      <section className="landing-blog">
        <div className="landing-blog-inner">
          <div className="landing-section-label">{lp.blogLabel}</div>
          <h2 className="landing-section-title">{lp.blogTitle}</h2>
          <div className="landing-blog-grid">
            {BLOG_POSTS.map(p => (
              <article key={p.id} className="blog-card" onClick={() => setBlogPost(p)}>
                <div className="blog-card-img">
                  <img src={p.image} alt={p.title} className="blog-card-photo" />
                  <div className="blog-card-img-overlay" style={{background: p.gradient}} />
                  <div className="blog-card-category">{p.category}</div>
                </div>
                <div className="blog-card-body">
                  <h3 className="blog-card-title">{p.title}</h3>
                  <p className="blog-card-excerpt">{p.excerpt}</p>
                  <div className="blog-card-footer">
                    <span className="blog-read-time">{p.readTime}</span>
                    <span className="blog-read-more">{lp.readArticle}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <div className="landing-footer-brand">
            <div className="landing-footer-logo">
              <img src={`${BASE}academia.svg`} alt="Academia" style={{height:'52px',width:'auto'}} />
            </div>
            <p className="landing-footer-tagline">{lp.footerTagline}</p>
            <div className="footer-socials">
              <a href="https://www.instagram.com/academiaproject2k26?igsh=dXZ1Ym5za2oyaWtu" target="_blank" rel="noopener noreferrer" className="footer-social-icon" title="Instagram">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M16 11.37A4 4 0 1112.63 8 4 4 0 0116 11.37z"/><circle cx="17.5" cy="6.5" r=".5" fill="currentColor" stroke="none"/></svg>
              </a>
              <a href="https://www.facebook.com/profile.php?id=61572029378538" target="_blank" rel="noopener noreferrer" className="footer-social-icon" title="Facebook">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 2h-3a5 5 0 00-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 011-1h3z"/></svg>
              </a>
              <a href="https://www.linkedin.com/company/academia-platform/" target="_blank" rel="noopener noreferrer" className="footer-social-icon" title="LinkedIn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-2-2 2 2 0 00-2 2v7h-4v-7a6 6 0 016-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg>
              </a>
            </div>
          </div>

          <div className="landing-footer-mail">
            <div className="footer-link-head">{lp.footerContactTitle}</div>
            <p className="footer-mail-desc">{lp.footerContactDesc} <a href="mailto:academiaproject2k26@gmail.com" className="footer-contact-email">academiaproject2k26@gmail.com</a></p>
            <div className="footer-link-head" style={{marginTop:"1.25rem"}}>{lp.footerStayTitle}</div>
            <p className="footer-mail-desc">{lp.footerStayDesc}</p>
            {mailSent ? (
              <div className="footer-mail-success">{lp.footerSubscribed}</div>
            ) : (
              <form className="footer-mail-form" onSubmit={e => { e.preventDefault(); setMailSent(true); }}>
                <input type="email" placeholder={lp.footerPlaceholder} required className="footer-mail-input" />
                <button type="submit" className="footer-mail-btn">{lp.footerSubscribe}</button>
              </form>
            )}
          </div>
        </div>
        <div className="landing-footer-bottom">
          <span>{lp.footerCopy}</span>
        </div>
      </footer>

      {/* Blog post modal */}
      {blogPost && (
        <div className="blog-modal-overlay" onClick={() => setBlogPost(null)}>
          <div className="blog-modal" onClick={e => e.stopPropagation()}>
            <div className="blog-modal-img">
              <img src={blogPost.image} alt={blogPost.title} className="blog-card-photo" />
              <div className="blog-card-img-overlay" style={{background: blogPost.gradient}} />
              <span className="blog-card-category">{blogPost.category}</span>
              <button className="blog-modal-close" onClick={() => setBlogPost(null)}>×</button>
            </div>
            <div className="blog-modal-body">
              <div className="blog-modal-meta">{blogPost.readTime}</div>
              <h2 className="blog-modal-title">{blogPost.title}</h2>
              <div className="blog-modal-content">
                {blogPost.content.split("\n\n").map((para, i) => (
                  <p key={i}>{para}</p>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function LoginPage({ onLogin, onBack }) {
  const { t, lang, toggleLang } = useContext(LangContext);
  const tl = t.login;
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const handleRegister = async (e) => {
    e.preventDefault();
    setError("");
    const fd = new FormData(e.target);
    const password  = fd.get("password");
    const password2 = fd.get("password2");
    if (password !== password2) return setError("Passwords don't match");
    if (password.length < 6)    return setError("Password must be at least 6 characters");

    setLoading(true);
    try {
      // Use FormData so we can include the optional avatar file
      const payload = new FormData();
      payload.append("email",      fd.get("email").toLowerCase().trim());
      payload.append("password",   password);
      payload.append("first_name", fd.get("first_name"));
      payload.append("last_name",  fd.get("last_name"));
      payload.append("role",       fd.get("role"));
      payload.append("phone",      fd.get("phone") || "");
      const avatarFile = fd.get("avatar");
      if (avatarFile && avatarFile.size > 0) payload.append("avatar", avatarFile);

      const res  = await fetch(`${API}/auth/register`, {
        method: "POST",
        body: payload,  // no Content-Type header — browser sets multipart boundary automatically
      });
      const data = await res.json();
      if (res.ok) {
        setMode("login");
        setError("OK Account created! Please log in.");
      } else {
        setError(data.error || "Registration failed");
      }
    } catch {
      setError("Connection error. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onLogin(e);
    } catch {
      setError("Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page" dir={lang === "ar" ? "rtl" : "ltr"}>
      <div className="login-card">
        <div className="login-top-row">
          <button className="login-back-btn" onClick={onBack}>{tl.back}</button>
        </div>
        <img src={`${BASE}academia.svg`} alt="Academia" className="login-logo" />

        <div className="auth-toggle">
          <button className={mode === "login"    ? "active" : ""} onClick={() => { setMode("login");    setError(""); }}>{tl.loginTab}</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => { setMode("register"); setError(""); }}>{tl.registerTab}</button>
        </div>

        {error && (
          <div className={`auth-msg ${error.startsWith("OK") ? "auth-msg-ok" : "auth-msg-err"}`}>
            {error}
          </div>
        )}

        {mode === "login" ? (
          <form onSubmit={handleLogin} className="login-form">
            <label>{tl.emailLabel}</label>
            <input name="email" type="email" placeholder={tl.emailPlaceholder} required />
            <label>{tl.passwordLabel}</label>
            <input name="password" type="password" placeholder={tl.passwordPlaceholder} required />
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? tl.loggingIn : tl.loginBtn}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="login-form">
            <div className="name-row">
              <div>
                <label>{tl.firstNameLabel}</label>
                <input name="first_name" placeholder="" required />
              </div>
              <div>
                <label>{tl.lastNameLabel}</label>
                <input name="last_name" placeholder="" required />
              </div>
            </div>
            <label>{tl.emailLabel}</label>
            <input name="email" type="email" placeholder={tl.emailPlaceholder} required />
            <label>{tl.roleLabel}</label>
            <select name="role" required>
              <option value="student">{tl.roleStudent}</option>
              <option value="professor">{tl.roleProfessor}</option>
            </select>
            <label>{tl.phoneLabel}</label>
            <input name="phone" type="tel" placeholder={tl.phonePlaceholder} required />
            <label>{tl.passwordLabel}</label>
            <input name="password" type="password" placeholder={tl.minPassword} required />
            <label>{tl.confirmPasswordLabel}</label>
            <input name="password2" type="password" placeholder={tl.confirmPasswordPlaceholder} required />
            <label>{tl.avatarLabel} <span style={{opacity:.5,fontSize:".8em"}}>({tl.optional})</span></label>
            <input name="avatar" type="file" accept=".jpg,.jpeg,.png,.webp" className="avatar-file-input" />
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? tl.creatingBtn : tl.createBtn}
            </button>
          </form>
        )}


      </div>
    </div>
  );
}

function Dashboard({ user, isProf, courses, assignments, announcements, quizzesSummary, attendanceRisk, myAttendance }) {
  const { t, lang } = useLang();
  const td = t.dashboard;
  // Only students should see deadline alerts — professors don't have submission_status
  const urgent = !isProf ? assignments.filter(a => {
    const d = daysUntil(a.due_date);
    return d >= 0 && d <= 3 && a.submission_status !== "submitted" && a.submission_status !== "graded";
  }) : [];

  // Calculate attendance rate directly from records as reliable fallback
  const calcAttRate = myAttendance && myAttendance.length > 0
    ? Math.round(myAttendance.filter(r => r.status === "present" || r.status === "late").length / myAttendance.length * 100)
    : null;
  const attRate = (attendanceRisk && attendanceRisk.total_classes > 0)
    ? Math.round(attendanceRisk.attendance_rate * 100)
    : calcAttRate;

  return (
    <div className="dashboard-grid">
      <div className="dash-card wide welcome-card">
        <h2>{isProf ? td.welcomeProf : td.welcomeStudent} {user.first_name}.</h2>
        <p>{isProf ? td.teachingLine(courses.length) : td.enrolledLine(courses.length)}</p>
      </div>

      {!isProf && (() => {
        const today = new Date().toISOString().slice(0, 10);
        const todayQuizzes = quizzesSummary.filter(q => {
          if (q.attempt_status) return false;
          if (q.quiz_date !== today) return false;
          if (!q.start_time) return true;
          const start = new Date(`${q.quiz_date}T${q.start_time}`);
          const end = new Date(start.getTime() + (q.duration_minutes || 1440) * 60000);
          const now = new Date();
          return now >= start && now <= end;
        });
        return todayQuizzes.length > 0 && (
          <div className="dash-card wide alert-card danger">
            <h3>Quiz Due Today!</h3>
            <p>You have {todayQuizzes.length === 1 ? "a quiz" : `${todayQuizzes.length} quizzes`} scheduled for today. Go to <b>Assignments &amp; Quizzes → Quizzes</b> to take {todayQuizzes.length === 1 ? "it" : "them"} now — access locks at {todayQuizzes.length === 1 && todayQuizzes[0].start_time && todayQuizzes[0].duration_minutes ? (() => { const s = new Date(`${todayQuizzes[0].quiz_date}T${todayQuizzes[0].start_time}`); const e = new Date(s.getTime() + todayQuizzes[0].duration_minutes * 60000); return `${e.getHours().toString().padStart(2,'0')}:${e.getMinutes().toString().padStart(2,'0')}`; })() : "midnight"}.</p>
            <div className="stat-row">
              {todayQuizzes.map(q => (
                <span key={q.quiz_id} className="stat-pill">{q.title} · {q.course_name} · {q.total_points} pts</span>
              ))}
            </div>
          </div>
        );
      })()}

      {!isProf && attendanceRisk && attendanceRisk.risk_level === "high" && (
        <div className="dash-card wide alert-card danger">
          <h3>Low Attendance Warning</h3>
          <p>{attendanceRisk.recommendation}</p>
          <div className="stat-row">
            <span className="stat-pill">Rate: {attRate}%</span>
            <span className="stat-pill">Absences: {attendanceRisk.absences}/{attendanceRisk.total_classes}</span>
          </div>
        </div>
      )}
      {!isProf && attendanceRisk && attendanceRisk.risk_level === "medium" && (
        <div className="dash-card wide alert-card warning">
          <h3>Attendance Notice</h3>
          <p>{attendanceRisk.recommendation}</p>
          <div className="stat-row">
            <span className="stat-pill">Rate: {attRate}%</span>
          </div>
        </div>
      )}

      <div className="dash-card stat-card">
        <div className="stat-icon">📚</div>
        <div className="stat-val">{n(courses.length, lang)}</div>
        <div className="stat-label">{isProf ? t.courses.myCourses : t.courses.enrolled}</div>
      </div>
      <div className="dash-card stat-card">
        <div className="stat-icon">📝</div>
        <div className="stat-val">{n(assignments.length, lang)}</div>
        <div className="stat-label">{t.assignments.assignSection}</div>
      </div>
      <div className="dash-card stat-card">
        <div className="stat-icon">📋</div>
        <div className="stat-val">
          {n(isProf
            ? quizzesSummary.length
            : quizzesSummary.length, lang)}
        </div>
        <div className="stat-label">{t.assignments.quizSection}</div>
      </div>
      {isProf && (
        <div className="dash-card stat-card">
          <div className="stat-icon">🔔</div>
          <div className="stat-val">{n(announcements.length, lang)}</div>
          <div className="stat-label">{t.sidebar.announcements}</div>
        </div>
      )}
      {!isProf && (
        <div className="dash-card stat-card">
          <div className="stat-val">{attRate !== null ? `${n(attRate, lang)}%` : "—"}</div>
          <div className="stat-label">{td.attendanceRate}</div>
        </div>
      )}

      {urgent.length > 0 && (
        <div className="dash-card wide">
          <h3>{td.urgent}</h3>
          {urgent.map(a => {
            const days = daysUntil(a.due_date);
            return (
              <div key={a.assignment_id} className="list-row">
                <div>
                  <b>{a.title}</b>
                  <span className="tag ml">{a.course_name}</span>
                </div>
                <span className={`tag ${days <= 1 ? "danger" : ""}`}
                  style={days > 1 ? {background:"#e8b84b",color:"#7a4f00",border:"none"} : {}}>
                  {days === 0 ? t.assignments.dueToday : `${days} ${t.assignments.daysLeft}`}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div className="dash-card wide">
        <h3>{td.announcements}</h3>
        {announcements.length === 0
          ? <p className="empty-msg">{td.noAnnouncements}</p>
          : announcements.slice(0, 3).map(a => (
            <div key={a.announcement_id} className="list-row col">
              <div className="row-top">
                <b>{a.title}</b>
                <span className="tag">{a.course_name || "General"}</span>
              </div>
              <p className="row-body">{a.content}</p>
              <span className="row-meta">{a.author_name} · {fmtDate(a.created_at)}</span>
            </div>
          ))
        }
      </div>
    </div>
  );
}

// Courses
function CoursesView({ isProf, courses, token, reload }) {
  const { t } = useLang();
  const tc = t.courses;
  const [modal, setModal] = useState(false);
  const [editCourse, setEditCourse] = useState(null); // course object being edited
  const [browseList, setBrowseList] = useState(null);

  const openBrowse = async () => {
    const res = await authFetch(`${API}/courses/all`, token);
    if (res.ok) setBrowseList((await res.json()).courses || []);
  };

  const createCourse = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const res = await authFetch(`${API}/courses`, token, {
      method: "POST",
      body: JSON.stringify({
        course_code: fd.get("course_code"), course_name: fd.get("course_name"),
        description: fd.get("description"), semester: fd.get("semester"), year: parseInt(fd.get("year")),
      }),
    });
    const data = await res.json();
    if (res.ok) { setModal(false); reload(); alert("Course created!"); }
    else alert("Error: " + (data.error || "Unknown error"));
  };

  const deleteCourse = async (course_id) => {
    if (!window.confirm("Delete this course? All enrollments and announcements will be removed.")) return;
    const res = await authFetch(`${API}/courses/${course_id}`, token, { method: "DELETE" });
    if (res.ok) { reload(); }
    else { const d = await res.json(); alert(d.error || "Failed to delete"); }
  };

  const updateCourse = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const res = await authFetch(`${API}/courses/${editCourse.course_id}`, token, {
      method: "PUT",
      body: JSON.stringify({ course_code: fd.get("course_code"), course_name: fd.get("course_name"), description: fd.get("description") }),
    });
    if (res.ok) { setEditCourse(null); reload(); }
    else { const d = await res.json(); alert(d.error || "Failed to update"); }
  };

  const enroll = async (course_id) => {
    const res = await authFetch(`${API}/courses/${course_id}/enroll`, token, { method: "POST" });
    const data = await res.json();
    if (res.ok) { setBrowseList(null); reload(); alert("Enrolled successfully!"); }
    else alert(data.error || "Error enrolling");
  };

  return (
    <div>
      <div className="view-actions">
        {isProf
          ? <button className="btn-primary" onClick={() => setModal(true)}>+ {tc.myCourses}</button>
          : <button className="btn-primary" onClick={openBrowse}>{tc.enrolled}</button>
        }
      </div>

      {courses.length === 0
        ? <div className="empty-state">{isProf ? tc.none : tc.none}</div>
        : <div className="course-grid">
            {courses.map(c => (
              <div key={c.course_id} className="course-card">
                <div className="course-code-badge">{c.course_code}</div>
                <h3>{c.course_name}</h3>
                <p className="course-desc">{c.description || t.common.noData}</p>
                <div className="course-footer">
                  <span>{c.semester} {c.year}</span>
                  <span>{c.instructor_name}</span>
                </div>
                {isProf && (
                  <div className="card-actions">
                    <button className="card-action-btn edit" onClick={() => setEditCourse(c)} title="Edit">✎</button>
                    <button className="card-action-btn delete" onClick={() => deleteCourse(c.course_id)} title="Delete">✕</button>
                  </div>
                )}
              </div>
            ))}
          </div>
      }

      {modal && (
        <Modal title={`+ ${tc.myCourses}`} onClose={() => setModal(false)}>
          <form onSubmit={createCourse} className="form">
            <Field label={tc.code} name="course_code" placeholder="CS101" required />
            <Field label={tc.myCourses} name="course_name" placeholder="Introduction to Computer Science" required />
            <Field label={t.assignments.descLabel} name="description" type="textarea" placeholder="What will students learn?" />
            <div className="field-row">
              <div className="field">
                <label>Semester</label>
                <select name="semester" required>
                  <option value="First Semester">{tc.sem1}</option>
                  <option value="Second Semester">{tc.sem2}</option>
                  <option value="Summer Course">{tc.semSummer}</option>
                </select>
              </div>
              <Field label="Year" name="year" type="number" defaultValue="2026" required />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setModal(false)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{t.common.create}</button>
            </div>
          </form>
        </Modal>
      )}

      {editCourse && (
        <Modal title={`Edit — ${editCourse.course_name}`} onClose={() => setEditCourse(null)}>
          <form onSubmit={updateCourse} className="form">
            <Field label={tc.code} name="course_code" defaultValue={editCourse.course_code} required />
            <Field label={tc.myCourses} name="course_name" defaultValue={editCourse.course_name} required />
            <Field label={t.assignments.descLabel} name="description" type="textarea" defaultValue={editCourse.description} />
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setEditCourse(null)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{t.common.save}</button>
            </div>
          </form>
        </Modal>
      )}

      {browseList && (
        <Modal title={tc.myCourses} onClose={() => setBrowseList(null)} wide>
          {browseList.length === 0
            ? <p className="empty-msg">{tc.none}</p>
            : <div className="course-grid">
                {browseList.map(c => (
                  <div key={c.course_id} className="course-card">
                    <div className="course-code-badge">{c.course_code}</div>
                    <h3>{c.course_name}</h3>
                    <p className="course-desc">{c.description}</p>
                    <div className="course-footer">
                      <span>{c.instructor_name}</span>
                      <span>{c.semester} {c.year}</span>
                    </div>
                    {c.is_enrolled
                      ? <div className="enrolled-badge">{tc.enrolled}</div>
                      : <button className="btn-enroll" onClick={() => enroll(c.course_id)}>{tc.enrolled}</button>
                    }
                  </div>
                ))}
              </div>
          }
        </Modal>
      )}
    </div>
  );
}

// --- Assignments ---
// Khalid asked me to add the grade display here
function AssignmentsView({ isProf, courses, assignments, token, reload }) {
  const { t } = useLang();
  const ta = t.assignments;
  const [modal, setModal]           = useState(false);
  const [editModal, setEditModal]   = useState(null); // assignment being edited
  const [detailModal, setDetailModal] = useState(null);
  const [tab, setTab] = useState("assignments"); // "assignments" | "quizzes"

  const createAssignment = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      course_id: fd.get("course_id"), title: fd.get("title"),
      description: fd.get("description"), due_date: fd.get("due_date"),
      points: parseInt(fd.get("points")),
    };
    if (!body.course_id || !body.title || !body.due_date) return alert("Please fill in all required fields!");

    const res = await authFetch(`${API}/assignments`, token, { method: "POST", body: JSON.stringify(body) });
    const data = await res.json();
    if (res.ok) { setModal(false); reload(); alert("Assignment created!"); }
    else alert((data.error || "Failed to create assignment"));
  };

  const deleteAssignment = async (assignment_id) => {
    if (!window.confirm("Delete this assignment? All submissions will be removed.")) return;
    const res = await authFetch(`${API}/assignments/${assignment_id}`, token, { method: "DELETE" });
    if (res.ok) reload();
    else { const d = await res.json(); alert(d.error || "Failed to delete"); }
  };

  const updateAssignment = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const res = await authFetch(`${API}/assignments/${editModal.assignment_id}`, token, {
      method: "PUT",
      body: JSON.stringify({ title: fd.get("title"), description: fd.get("description"), due_date: fd.get("due_date"), points: parseInt(fd.get("points")) }),
    });
    if (res.ok) { setEditModal(null); reload(); }
    else { const d = await res.json(); alert(d.error || "Failed to update"); }
  };

  const submitAssignment = async (assignment_id, notes, file) => {
    let res;
    if (file) {
      const fd = new FormData();
      fd.append("notes", notes);
      fd.append("file", file);
      res = await fetch(`${API}/assignments/${assignment_id}/submit`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
    } else {
      res = await authFetch(`${API}/assignments/${assignment_id}/submit`, token, {
        method: "POST", body: JSON.stringify({ notes }),
      });
    }
    const data = await res.json();
    if (res.ok) { setDetailModal(null); reload(); alert("Assignment submitted!"); }
    else alert("Error: " + (data.error || "something went wrong, try again"));
  };

  const renderCard = (a) => {
    const days = daysUntil(a.due_date);
    const isDone = !isProf && ["submitted","graded"].includes(a.submission_status);
    const isPastDue = days < 0;
    const dueCls = isPastDue ? (isProf ? "info" : "danger") : days <= 3 ? "warning" : "success";
    const dueLbl = isPastDue ? (isProf ? ta.closed : ta.overdue) : days === 0 ? ta.dueToday : `${days} ${ta.daysLeft}`;
    return (
      <div key={a.assignment_id} className="assignment-card" onClick={() => setDetailModal(a)}>
        <div className="asgn-left">
          <span className="tag info">{a.course_name}</span>
          <h3 className="asgn-title">{a.title}</h3>
          <p className="asgn-desc">{a.description || t.common.noData}</p>
        </div>
        <div className="asgn-right">
          {isDone
            ? <span className="tag success">{a.submission_status === "graded" ? `${ta.graded}: ${a.score}/${a.points}` : ta.submitted}</span>
            : <span className={`tag ${dueCls}`}>{dueLbl}</span>
          }
          <span className="asgn-points">{a.points} {ta.points}</span>
          <span className="asgn-due">{ta.dueDate}: {fmtDate(a.due_date)}</span>
          {!isProf && !isDone && (
            <span className="sub-status">{ta.notSubmitted}</span>
          )}
          {isProf && <span className="sub-count">{a.submission_count || 0} {ta.submissions}</span>}
          {isProf && (
            <div className="card-actions" onClick={e => e.stopPropagation()}>
              <button className="card-action-btn edit" onClick={() => setEditModal(a)} title="Edit">✎</button>
              <button className="card-action-btn delete" onClick={() => deleteAssignment(a.assignment_id)} title="Delete">✕</button>
            </div>
          )}
        </div>
      </div>
    );
  };

  const pending   = assignments.filter(a => !isProf && !["submitted","graded"].includes(a.submission_status));
  const completed = assignments.filter(a => !isProf && ["submitted","graded"].includes(a.submission_status));

  return (
    <div>
      {/* Tab switcher */}
      <div className="quiz-tab-bar">
        <button className={`quiz-tab ${tab === "assignments" ? "active" : ""}`} onClick={() => setTab("assignments")}>{ta.assignSection}</button>
        <button className={`quiz-tab ${tab === "quizzes" ? "active" : ""}`} onClick={() => setTab("quizzes")}>{ta.quizSection}</button>
      </div>

      {tab === "quizzes" && (
        <QuizzesView isProf={isProf} courses={courses} token={token} />
      )}

      {tab === "assignments" && <>
      <div className="view-actions">
        {isProf && <button className="btn-primary" onClick={() => setModal(true)}>{ta.createAssignment}</button>}
      </div>

      {assignments.length === 0
        ? <div className="empty-state">{isProf ? ta.noProfAssignments : ta.noStudentAssignments}</div>
        : isProf
          ? <div className="assignments-list">{[...assignments].sort((a, b) => {
              const today = new Date().toISOString().slice(0,10);
              const aClosed = a.due_date < today ? 1 : 0;
              const bClosed = b.due_date < today ? 1 : 0;
              if (aClosed !== bClosed) return aClosed - bClosed;
              return new Date(a.due_date) - new Date(b.due_date);
            }).map(renderCard)}</div>
          : <>
              <div style={{marginBottom:"1.5rem"}}>
                <h3 style={{margin:"0 0 0.75rem",fontSize:"1rem",fontWeight:700,color:"var(--text)",display:"flex",alignItems:"center",gap:"0.5rem"}}>
                  {ta.pending} <span style={{background:"var(--danger)",color:"#fff",borderRadius:"12px",padding:"0.1rem 0.55rem",fontSize:"0.78rem"}}>{pending.length}</span>
                </h3>
                {pending.length === 0
                  ? <p style={{color:"var(--mid)",fontSize:"0.9rem"}}>{ta.noPending}</p>
                  : <div className="assignments-list">{pending.map(renderCard)}</div>
                }
              </div>
              <div>
                <h3 style={{margin:"0 0 0.75rem",fontSize:"1rem",fontWeight:700,color:"var(--text)",display:"flex",alignItems:"center",gap:"0.5rem"}}>
                  {ta.completedTab} <span style={{background:"var(--ok,#16a34a)",color:"#fff",borderRadius:"12px",padding:"0.1rem 0.55rem",fontSize:"0.78rem"}}>{completed.length}</span>
                </h3>
                {completed.length === 0
                  ? <p style={{color:"var(--mid)",fontSize:"0.9rem"}}>{ta.noCompleted}</p>
                  : <div className="assignments-list">{completed.map(renderCard)}</div>
                }
              </div>
            </>
      }

      {modal && (
        <Modal title={ta.createTitle} onClose={() => setModal(false)}>
          <form onSubmit={createAssignment} className="form">
            <div className="field">
              <label>{ta.courseRequired}</label>
              <select name="course_id" required>
                <option value="">— {t.common.all} —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name} ({c.course_code})</option>)}
              </select>
            </div>
            <Field label={ta.titleRequired} name="title" placeholder={ta.assignTitle} required />
            <Field label={ta.descLabel} name="description" type="textarea" placeholder={ta.instructions} />
            <div className="field-row">
              <Field label={ta.dueDateRequired} name="due_date" type="date" min={new Date().toISOString().split('T')[0]} required />
              <Field label={ta.pointsRequired} name="points" type="number" placeholder="100" min="1" max="100" required />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setModal(false)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{ta.createTitle}</button>
            </div>
          </form>
        </Modal>
      )}

      {detailModal && (
        <AssignmentDetail
          assignment={detailModal}
          isProf={isProf}
          token={token}
          onSubmit={submitAssignment}
          onClose={() => setDetailModal(null)}
        />
      )}

      {editModal && (
        <Modal title={`Edit — ${editModal.title}`} onClose={() => setEditModal(null)}>
          <form onSubmit={updateAssignment} className="form">
            <Field label={ta.titleRequired} name="title" defaultValue={editModal.title} required />
            <Field label={ta.descLabel} name="description" type="textarea" defaultValue={editModal.description} />
            <div className="field-row">
              <Field label={ta.dueDateRequired} name="due_date" type="date" defaultValue={editModal.due_date} required />
              <Field label={ta.pointsRequired} name="points" type="number" defaultValue={editModal.points} min="1" max="100" required />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setEditModal(null)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{t.common.save}</button>
            </div>
          </form>
        </Modal>
      )}
      </>}
    </div>
  );
}

function AssignmentDetail({ assignment: a, isProf, token, onSubmit, onClose }) {
  const { t } = useLang();
  const ta = t.assignments;
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState(null);
  const [submissions, setSubmissions] = useState([]);

  useEffect(() => {
    if (isProf) {
      authFetch(`${API}/assignments/${a.assignment_id}/submissions`, token)
        .then(r => r.json()).then(d => setSubmissions(d.submissions || []));
    }
  }, [a.assignment_id, isProf, token]);

  const canSubmit = !isProf && a.submission_status === "not_submitted";

  return (
    <Modal title={a.title} onClose={onClose}>
      <div className="detail-body">
        <div className="detail-meta">
          <span className="tag info">{a.course_name}</span>
          <span className="tag">{a.points} {ta.points}</span>
          <span className="tag">{ta.dueDate}: {fmtDate(a.due_date)}</span>
        </div>
        <p className="detail-desc">{a.description || t.common.noData}</p>

        {canSubmit && (
          <div className="submit-section">
            <h4>{ta.submitWork}</h4>
            <textarea className="submit-notes" rows={3} placeholder={ta.addNotes}
              value={notes} onChange={e => setNotes(e.target.value)} />
            <div className="submit-file-row">
              <label className="submit-file-label">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                {file ? file.name : ta.attachFile}
                <input type="file" style={{display:"none"}} accept=".pdf,.doc,.docx,.ppt,.pptx,.zip,.txt,.png,.jpg"
                  onChange={e => setFile(e.target.files[0] || null)} />
              </label>
              {file && <button className="btn-secondary" style={{padding:"0.25rem 0.6rem",fontSize:"0.8rem"}} onClick={() => setFile(null)}>{ta.remove}</button>}
            </div>
            <button className="btn-primary" onClick={() => onSubmit(a.assignment_id, notes, file)}>
              {ta.submitBtn}
            </button>
          </div>
        )}

        {!isProf && a.submission_status === "submitted" && (
          <div className="submitted-banner">{ta.submittedBanner}</div>
        )}

        {!isProf && a.submission_status === "graded" && (
          a.feedback === "Not submitted by deadline — automatically graded 0." ? (
            <div className="grade-banner grade-banner-closed">
              <div className="grade-score">
                {ta.grade}: <strong>0/{a.points} {ta.points}</strong>
                <span className="grade-pct"> (0%)</span>
              </div>
              <div className="grade-feedback">
                <p className="grade-feedback-text">{ta.closed}</p>
              </div>
            </div>
          ) : (
            <div className="grade-banner">
              <div className="grade-score">{ta.grade}: <strong>{a.score}/{a.points} {ta.points}</strong>
                <span className="grade-pct"> ({a.points > 0 ? Math.round(a.score/a.points*100) : 0}%)</span>
              </div>
              {a.feedback && (
                <div className="grade-feedback">
                  <span className="grade-feedback-label">{ta.professorFeedback}</span>
                  <p className="grade-feedback-text">{a.feedback}</p>
                </div>
              )}
            </div>
          )
        )}

        {isProf && (
          <div className="submissions-list">
            <div className="submissions-header">
              <h4>{ta.studentSubmissions} ({submissions.length})</h4>
              {submissions.length > 0 && (
                <span className="tag info">{submissions.filter(s=>s.status==="graded").length}/{submissions.length} {ta.graded}</span>
              )}
            </div>
            {submissions.length === 0
              ? <div className="empty-state" style={{padding:"2rem"}}>No submissions yet</div>
              : submissions.map(s => (
                <SubmissionCard key={s.submission_id} submission={s} assignment={a} token={token}
                  onGraded={() => {
                    authFetch(`${API}/assignments/${a.assignment_id}/submissions`, token)
                      .then(r=>r.json()).then(d=>setSubmissions(d.submissions||[]));
                  }}
                />
              ))
            }
          </div>
        )}
      </div>
    </Modal>
  );
}

function QuizTimer({ endTime, onExpire }) {
  const [remaining, setRemaining] = useState(Math.max(0, endTime - Date.now()));
  useEffect(() => {
    const iv = setInterval(() => {
      const left = Math.max(0, endTime - Date.now());
      setRemaining(left);
      if (left === 0) { clearInterval(iv); onExpire(); }
    }, 1000);
    return () => clearInterval(iv);
  }, [endTime]);
  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  return (
    <div className={`quiz-timer${remaining < 300000 ? " urgent" : ""}`}>
      ⏱ {mins}:{String(secs).padStart(2, "0")} remaining
    </div>
  );
}

function QuizzesView({ isProf, courses, token }) {
  const { t } = useLang();
  const tq = t.assignments;
  const [quizzes, setQuizzes] = useState([]);
  const [createModal, setCreateModal] = useState(false);
  const [editQuizModal, setEditQuizModal] = useState(null); // quiz being edited
  const [takeModal, setTakeModal] = useState(null);   // quiz object with questions
  const [resultsModal, setResultsModal] = useState(null); // {quiz, results}
  const [reviewModal, setReviewModal] = useState(null); // student review of own attempt
  const [questions, setQuestions] = useState([{ question_text:"", option_a:"", option_b:"", option_c:"", option_d:"", correct_option:"A" }]);
  const [submitting, setSubmitting] = useState(false);
  const [answers, setAnswers] = useState({});

  const today = new Date().toISOString().split("T")[0];

  const load = useCallback(async () => {
    const r = await authFetch(`${API}/quizzes`, token);
    const d = await r.json();
    if (r.ok) setQuizzes(d.quizzes || []);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const addQuestion = () => setQuestions(prev => [...prev, { question_text:"", option_a:"", option_b:"", option_c:"", option_d:"", correct_option:"A" }]);
  const removeQuestion = (i) => setQuestions(prev => prev.filter((_,idx) => idx !== i));
  const updateQuestion = (i, field, val) => setQuestions(prev => prev.map((q,idx) => idx===i ? {...q,[field]:val} : q));

  const createQuiz = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      course_id: fd.get("course_id"), title: fd.get("title"),
      description: fd.get("description"), quiz_date: fd.get("quiz_date"),
      start_time: fd.get("start_time"),
      duration_minutes: parseInt(fd.get("duration_minutes")) || null,
      questions,
    };
    if (!body.course_id || !body.title || !body.quiz_date || !body.start_time || !body.duration_minutes) return alert("Please fill all required fields.");
    if (questions.some(q => !q.question_text || !q.option_a || !q.option_b || !q.option_c || !q.option_d)) return alert("Please fill in all question fields.");
    const r = await authFetch(`${API}/quizzes`, token, { method:"POST", body: JSON.stringify(body) });
    const d = await r.json();
    if (r.ok) { setCreateModal(false); setQuestions([{ question_text:"", option_a:"", option_b:"", option_c:"", option_d:"", correct_option:"A" }]); load(); alert("Quiz created and announcement posted!"); }
    else alert(d.error || "Failed to create quiz");
  };

  const openQuiz = async (qz) => {
    if (qz.attempt_status === "submitted") return alert(`You already completed this quiz. Score: ${qz.score}/${qz.question_count}`);
    const now = new Date();
    const start = new Date(`${qz.quiz_date}T${qz.start_time || "00:00"}`);
    const end = new Date(start.getTime() + (qz.duration_minutes || 1440) * 60000);
    if (now < start) return alert(`This quiz opens at ${qz.start_time} on ${fmtDate(qz.quiz_date)}.`);
    if (now > end) return alert(`This quiz window has closed.`);
    const r = await authFetch(`${API}/quizzes/${qz.quiz_id}`, token);
    const d = await r.json();
    if (r.ok) { setAnswers({}); setTakeModal({ ...d, quiz_date: qz.quiz_date, start_time: qz.start_time, duration_minutes: qz.duration_minutes }); }
    else alert(d.error || "Cannot open quiz");
  };

  const submitQuiz = async () => {
    if (!takeModal) return;
    console.log("submitting quiz", takeModal.quiz_id, answers);
    const unanswered = takeModal.questions.filter(q => !answers[q.question_id]);
    if (unanswered.length > 0) { if (!window.confirm(`You have ${unanswered.length} unanswered question(s). Submit anyway?`)) return; }
    setSubmitting(true);
    const r = await authFetch(`${API}/quizzes/${takeModal.quiz_id}/attempt`, token, { method:"POST", body: JSON.stringify({ answers }) });
    const d = await r.json();
    setSubmitting(false);
    if (r.ok) { setTakeModal(null); load(); alert(`Quiz submitted! You scored ${d.score}/${d.total}.`); }
    else alert(d.error || "Failed to submit quiz");
  };

  const viewResults = async (qz) => {
    const r = await authFetch(`${API}/quizzes/${qz.quiz_id}/results`, token);
    const d = await r.json();
    if (r.ok) setResultsModal({ quiz: qz, results: d.results || [] });
  };

  const deleteQuiz = async (quiz_id) => {
    if (!window.confirm("Delete this quiz? All student attempts will be removed.")) return;
    const res = await authFetch(`${API}/quizzes/${quiz_id}`, token, { method: "DELETE" });
    if (res.ok) load();
    else { const d = await res.json(); alert(d.error || "Failed to delete"); }
  };

  const updateQuiz = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const res = await authFetch(`${API}/quizzes/${editQuizModal.quiz_id}`, token, {
      method: "PUT",
      body: JSON.stringify({ title: fd.get("title"), description: fd.get("description"), quiz_date: fd.get("quiz_date"), start_time: fd.get("start_time"), duration_minutes: parseInt(fd.get("duration_minutes")) || null }),
    });
    if (res.ok) { setEditQuizModal(null); load(); }
    else { const d = await res.json(); alert(d.error || "Failed to update"); }
  };

  const openReview = async (qz) => {
    const r = await authFetch(`${API}/quizzes/${qz.quiz_id}/review`, token);
    const d = await r.json();
    if (r.ok) setReviewModal({ quiz: qz, ...d });
    else alert(d.error || "Could not load review");
  };

  const getStatusBadge = (qz) => {
    const now = new Date();
    const start = qz.start_time ? new Date(`${qz.quiz_date}T${qz.start_time}`) : new Date(`${qz.quiz_date}T00:00`);
    const end = new Date(start.getTime() + (qz.duration_minutes || 1440) * 60000);
    const isLive = now >= start && now <= end;
    if (isProf) {
      return isLive ? <span className="tag warning">Live Now</span>
           : qz.quiz_date > today ? <span className="tag info">Upcoming</span>
           : <span className="tag">Past</span>;
    }
    if (qz.attempt_status === "submitted") return <span className="tag success">Scored {qz.score}/{qz.question_count}</span>;
    if (qz.attempt_status === "graded_zero") return <span className="tag danger">Missed — 0/{qz.question_count}</span>;
    if (isLive) return <span className="tag warning">Available Now</span>;
    if (qz.quiz_date > today) return <span className="tag info">Upcoming</span>;
    return <span className="tag">Closed</span>;
  };

  return (
    <div>
      <div className="view-actions">
        {isProf && <button className="btn-primary" onClick={() => setCreateModal(true)}>+ {tq.quizSection}</button>}
      </div>

      {quizzes.length === 0
        ? <div className="empty-state">{tq.noQuizzes}</div>
        : <div className="quiz-list">
            {quizzes.map(qz => (
              <div key={qz.quiz_id} className="quiz-card">
                <div className="quiz-card-left">
                  <div className="quiz-card-title">{qz.title}</div>
                  <div className="quiz-card-meta">{qz.course_name} · {qz.question_count} {tq.questions} · {fmtDate(qz.quiz_date)}{qz.start_time ? ` at ${qz.start_time}` : ""}{qz.duration_minutes ? ` · ${qz.duration_minutes} min` : ""}</div>
                </div>
                <div className="quiz-card-right">
                  {getStatusBadge(qz)}
                  {!isProf && (() => {
                    const now = new Date();
                    const start = qz.start_time ? new Date(`${qz.quiz_date}T${qz.start_time}`) : new Date(`${qz.quiz_date}T00:00`);
                    const end = new Date(start.getTime() + (qz.duration_minutes || 1440) * 60000);
                    return now >= start && now <= end && !qz.attempt_status ? (
                      <button className="btn-primary quiz-btn" onClick={() => openQuiz(qz)}>{tq.startQuiz}</button>
                    ) : null;
                  })()}
                  {!isProf && qz.attempt_status === "submitted" && qz.quiz_date < today && (
                    <button className="btn-secondary quiz-btn" onClick={() => openReview(qz)}>{tq.reviewAnswers || "Review"}</button>
                  )}
                  {isProf && qz.quiz_date <= today && (
                    <button className="btn-secondary quiz-btn" onClick={() => viewResults(qz)}>{tq.attempt}</button>
                  )}
                  {isProf && (
                    <div className="card-actions">
                      <button className="card-action-btn edit" onClick={() => setEditQuizModal(qz)} title="Edit">✎</button>
                      <button className="card-action-btn delete" onClick={() => deleteQuiz(qz.quiz_id)} title="Delete">✕</button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
      }

      {/* Edit Quiz Modal */}
      {editQuizModal && (
        <Modal title={`Edit — ${editQuizModal.title}`} onClose={() => setEditQuizModal(null)}>
          <form onSubmit={updateQuiz} className="form">
            <Field label="Quiz Title *" name="title" defaultValue={editQuizModal.title} required />
            <Field label="Description" name="description" type="textarea" defaultValue={editQuizModal.description} />
            <Field label="Quiz Date *" name="quiz_date" type="date" defaultValue={editQuizModal.quiz_date} required />
            <Field label="Start Time *" name="start_time" type="time" defaultValue={editQuizModal.start_time} required />
            <Field label="Duration (minutes) *" name="duration_minutes" type="number" defaultValue={editQuizModal.duration_minutes} placeholder="e.g. 60" required />
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setEditQuizModal(null)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{t.common.save}</button>
            </div>
          </form>
        </Modal>
      )}

      {/* Create Quiz Modal */}
      {createModal && (
        <Modal title="Create New Quiz" onClose={() => setCreateModal(false)} wide>
          <form onSubmit={createQuiz} className="form">
            <div className="field">
              <label>Course *</label>
              <select name="course_id" required>
                <option value="">— Select a course —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name} ({c.course_code})</option>)}
              </select>
            </div>
            <Field label="Quiz Title *" name="title" placeholder="e.g. Chapter 3 Quiz" required />
            <Field label="Description" name="description" type="textarea" placeholder="Optional instructions…" />
            <Field label="Quiz Date *" name="quiz_date" type="date" min={today} required />
            <Field label="Start Time *" name="start_time" type="time" required />
            <Field label="Duration (minutes) *" name="duration_minutes" type="number" placeholder="e.g. 60" required />

            <div className="quiz-questions-header">
              <span>Questions ({questions.length})</span>
              <button type="button" className="btn-secondary" style={{padding:".3rem .8rem",fontSize:".82rem"}} onClick={addQuestion}>+ Add Question</button>
            </div>

            {questions.map((q, i) => (
              <div key={i} className="quiz-question-block">
                <div className="quiz-q-header">
                  <span className="quiz-q-num">Q{i+1}</span>
                  {questions.length > 1 && <button type="button" className="quiz-q-remove" onClick={() => removeQuestion(i)}>Remove</button>}
                </div>
                <div className="field">
                  <label>Question Text *</label>
                  <input type="text" value={q.question_text} onChange={e => updateQuestion(i,"question_text",e.target.value)} placeholder="Enter the question…" required />
                </div>
                <div className="quiz-options-grid">
                  {["a","b","c","d"].map(opt => (
                    <div key={opt} className="field">
                      <label>Option {opt.toUpperCase()} *</label>
                      <input type="text" value={q[`option_${opt}`]} onChange={e => updateQuestion(i,`option_${opt}`,e.target.value)} placeholder={`Option ${opt.toUpperCase()}`} required />
                    </div>
                  ))}
                </div>
                <div className="field">
                  <label>Correct Answer *</label>
                  <select value={q.correct_option} onChange={e => updateQuestion(i,"correct_option",e.target.value)}>
                    <option value="A">A</option><option value="B">B</option>
                    <option value="C">C</option><option value="D">D</option>
                  </select>
                </div>
              </div>
            ))}

            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setCreateModal(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Create Quiz</button>
            </div>
          </form>
        </Modal>
      )}

      {/* Take Quiz Modal */}
      {takeModal && (
        <Modal title={takeModal.title} onClose={() => setTakeModal(null)} wide>
          {takeModal.start_time && takeModal.duration_minutes && (
            <QuizTimer
              endTime={new Date(`${takeModal.quiz_date}T${takeModal.start_time}`).getTime() + takeModal.duration_minutes * 60000}
              onExpire={submitQuiz}
            />
          )}
          <div className="quiz-take-meta">{takeModal.course_name} · {takeModal.questions.length} questions · 1 point each</div>
          <div className="quiz-take-questions">
            {takeModal.questions.map((q, i) => (
              <div key={q.question_id} className="quiz-take-q">
                <div className="quiz-take-q-text">Q{i+1}. {q.question_text}</div>
                <div className="quiz-take-options">
                  {["A","B","C","D"].map(opt => (
                    <label key={opt} className={`quiz-option-label ${answers[q.question_id] === opt ? "selected" : ""}`}>
                      <input type="radio" name={q.question_id} value={opt} checked={answers[q.question_id]===opt} onChange={() => setAnswers(prev => ({...prev,[q.question_id]:opt}))} />
                      <span className="quiz-option-letter">{opt}</span>
                      <span>{q[`option_${opt.toLowerCase()}`]}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button className="btn-secondary" onClick={() => setTakeModal(null)}>Cancel</button>
            <button className="btn-primary" onClick={submitQuiz} disabled={submitting}>{submitting ? "Submitting…" : "Submit Quiz"}</button>
          </div>
        </Modal>
      )}

      {/* Student Review Modal — only visible after quiz date passes */}
      {reviewModal && (
        <Modal title={`${tq.reviewAnswers}: ${reviewModal.quiz.title}`} onClose={() => setReviewModal(null)} wide>
          <div className="quiz-review-header">
            <span className="quiz-review-score">
              {tq.score}: <strong>{reviewModal.score}/{reviewModal.total}</strong>
            </span>
            <span className={`tag ${reviewModal.score === reviewModal.total ? "success" : reviewModal.score >= reviewModal.total * 0.5 ? "warning" : "danger"}`}>
              {Math.round(reviewModal.score / reviewModal.total * 100)}%
            </span>
          </div>
          <div className="quiz-review-list">
            {(reviewModal.questions || []).map((q, i) => (
              <div key={q.question_id} className={`quiz-review-q ${q.is_correct ? "correct" : "incorrect"}`}>
                <div className="quiz-review-q-header">
                  <span className="quiz-review-num">Q{i + 1}</span>
                  <span className={`quiz-review-verdict ${q.is_correct ? "correct" : "incorrect"}`}>
                    {q.is_correct ? `✓ ${tq.correctAnswer}` : `✗ ${tq.yourAnswer}`}
                  </span>
                </div>
                <div className="quiz-review-q-text">{q.question_text}</div>
                <div className="quiz-review-options">
                  {["A","B","C","D"].map(opt => {
                    const isCorrect  = (q.correct_option  || "").toUpperCase() === opt;
                    const isStudents = (q.student_answer  || "").toUpperCase() === opt;
                    return (
                      <div key={opt} className={`quiz-review-option ${isCorrect ? "is-correct" : ""} ${isStudents && !isCorrect ? "is-wrong" : ""}`}>
                        <span className="quiz-option-letter">{opt}</span>
                        <span>{q[`option_${opt.toLowerCase()}`]}</span>
                        <span style={{marginLeft:"auto",display:"flex",gap:"4px",flexShrink:0}}>
                          {isStudents && <span className={`quiz-rev-tag ${isCorrect ? "correct-tag" : "wrong-tag"}`}>{isCorrect ? "Your Answer ✓" : "Your Answer ✗"}</span>}
                          {isCorrect && !isStudents && <span className="quiz-rev-tag correct-tag">Correct Answer</span>}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </Modal>
      )}

      {/* Results Modal */}
      {resultsModal && (
        <Modal title={`Results: ${resultsModal.quiz.title}`} onClose={() => setResultsModal(null)} wide>
          <div className="quiz-results-meta">{resultsModal.quiz.course_name} · {resultsModal.quiz.question_count} questions · {resultsModal.results.length} attempts</div>
          {resultsModal.results.length === 0
            ? <p style={{color:"var(--text-mid)",padding:"1rem 0"}}>No attempts yet.</p>
            : <table className="quiz-results-table">
                <thead><tr><th>Student</th><th>Score</th><th>Status</th><th>Submitted</th></tr></thead>
                <tbody>
                  {resultsModal.results.map(r => (
                    <tr key={r.attempt_id}>
                      <td>{r.student_name}<br/><span style={{fontSize:".78rem",color:"var(--text-mid)"}}>{r.email}</span></td>
                      <td><strong>{r.score}/{r.total}</strong></td>
                      <td><span className={`tag ${r.status==="submitted"?"success":"danger"}`}>{r.status==="submitted"?"Completed":"Missed"}</span></td>
                      <td style={{fontSize:".82rem",color:"var(--text-mid)"}}>{r.submitted_at ? fmtDate(r.submitted_at.split("T")[0]) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
          }
        </Modal>
      )}
    </div>
  );
}

// Attendance view
function AttendanceView({ isProf, courses, token, user, myAttendance, reload }) {
  const { t } = useLang();
  const tatt = t.attendance;
  const [modal, setModal]   = useState(false);
  const [students, setStudents] = useState([]);
  const [selCourse, setSelCourse] = useState("");
  const [records, setRecords] = useState([]);

  // bulk attendance state
  const [bulkModal, setBulkModal] = useState(false);
  const [bulkCourse, setBulkCourse] = useState("");
  const [bulkStudents, setBulkStudents] = useState([]);
  const [bulkDate, setBulkDate] = useState(new Date().toISOString().split("T")[0]);
  const [bulkStatuses, setBulkStatuses] = useState({});
  const [bulkSubmitting, setBulkSubmitting] = useState(false);

  const loadStudents = async (course_id) => {
    setSelCourse(course_id);
    if (!course_id) return;
    const res = await authFetch(`${API}/attendance/students/${course_id}`, token);
    if (res.ok) setStudents((await res.json()).students || []);
    const recRes = await authFetch(`${API}/attendance/course/${course_id}`, token);
    if (recRes.ok) setRecords((await recRes.json()).attendance || []);
  };

  const loadBulkStudents = async (course_id) => {
    setBulkCourse(course_id);
    if (!course_id) { setBulkStudents([]); setBulkStatuses({}); return; }
    const res = await authFetch(`${API}/attendance/students/${course_id}`, token);
    if (res.ok) {
      const list = (await res.json()).students || [];
      setBulkStudents(list);
      const init = {};
      list.forEach(s => { init[s.user_id] = "present"; });
      setBulkStatuses(init);
    }
  };

  const markAllPresent = () => {
    const updated = {};
    bulkStudents.forEach(s => { updated[s.user_id] = "present"; });
    setBulkStatuses(updated);
  };

  const submitBulk = async () => {
    if (!bulkCourse) return alert("Select a course");
    if (bulkStudents.length === 0) return alert("No students in this course");
    setBulkSubmitting(true);
    const records_payload = bulkStudents.map(s => ({ student_id: s.user_id, status: bulkStatuses[s.user_id] || "present" }));
    const res = await authFetch(`${API}/attendance/mark-bulk`, token, {
      method: "POST",
      body: JSON.stringify({ course_id: bulkCourse, date: bulkDate, records: records_payload })
    });
    const data = await res.json();
    setBulkSubmitting(false);
    if (res.ok) {
      alert(data.message);
      setBulkModal(false);
      loadStudents(bulkCourse);
      reload();
    } else {
      alert("Error: " + (data.error || "Unknown"));
    }
  };

  const markAttendance = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (!fd.get("student_id")) return alert("Please select a student");
    const body = { student_id: fd.get("student_id"), course_id: fd.get("course_id"), date: fd.get("date"), status: fd.get("status") };
    const res = await authFetch(`${API}/attendance/mark`, token, { method: "POST", body: JSON.stringify(body) });
    const data = await res.json();
    if (res.ok) { alert("Attendance recorded!"); setModal(false); loadStudents(body.course_id); reload(); }
    else alert("Error: " + (data.error || "Unknown"));
  };

  // Student view — attendance history
  if (!isProf) {
    const byCourse = {};
    myAttendance.forEach(r => {
      if (!byCourse[r.course_name]) byCourse[r.course_name] = [];
      byCourse[r.course_name].push(r);
    });

    return (
      <div>
        {myAttendance.length === 0
          ? <div className="empty-state">{tatt.noRecords}</div>
          : Object.entries(byCourse).map(([course, recs]) => {
              const present = recs.filter(r => !["absent","unexcused"].includes(r.status)).length;
              const pct = recs.length > 0 ? (present / recs.length) * 100 : 0;
              return (
                <div key={course} className="att-course-section">
                  <div className="att-course-header">
                    <h3>{course}</h3>
                    <span className={`att-pct-badge ${pct >= 75 ? "ok" : "low"}`}>{pct.toFixed(0)}% {tatt.rate}</span>
                  </div>
                  <div className="att-table-wrap">
                    <table className="att-table">
                      <thead><tr><th>{tatt.date}</th><th>{tatt.status}</th></tr></thead>
                      <tbody>
                        {recs.map(r => (
                          <tr key={r.attendance_id}>
                            <td>{fmtDate(r.date)}</td>
                            <td><span className={`att-status ${r.status}`}>
                              {r.status === "present" ? tatt.present : r.status === "absent" ? tatt.absent : tatt.late}
                            </span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })
        }
      </div>
    );
  }

  // Professor view
  return (
    <div>
      <div className="view-actions">
        <button className="btn-primary" onClick={() => setModal(true)}>+ {tatt.markAttendance}</button>
        <button className="btn-secondary" onClick={() => { setBulkModal(true); setBulkCourse(""); setBulkStudents([]); setBulkStatuses({}); }}>{tatt.save}</button>
      </div>

      <div className="field" style={{ marginBottom: "1.5rem", maxWidth: 400 }}>
        <label>{tatt.course}</label>
        <select value={selCourse} onChange={e => loadStudents(e.target.value)}>
          <option value="">— {tatt.allCourses} —</option>
          {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
        </select>
      </div>

      {selCourse && records.length > 0 && (
        <>
          <div style={{display:"flex",justifyContent:"flex-end",marginBottom:"0.75rem"}}>
            <button className="btn-secondary" onClick={() => {
              const courseName = courses.find(c => c.course_id === selCourse)?.course_name || "course";
              const rows = [["Student","Email","Date","Status"]];
              records.forEach(r => rows.push([`${r.first_name} ${r.last_name}`, r.email || "", r.date, r.status]));
              const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g,'""')}"`).join(",")).join("\n");
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url; a.download = `attendance_${courseName.replace(/\s+/g,"_")}.csv`; a.click();
              URL.revokeObjectURL(url);
            }}>Export CSV</button>
          </div>
          <div className="att-table-wrap">
            <table className="att-table">
              <thead><tr><th>Student</th><th>Date</th><th>Status</th></tr></thead>
              <tbody>
                {records.map(r => (
                  <tr key={r.attendance_id}>
                    <td>{r.first_name} {r.last_name}</td>
                    <td>{fmtDate(r.date)}</td>
                    <td><span className={`att-status ${r.status}`}>{r.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {modal && (
        <Modal title="Mark Attendance" onClose={() => setModal(false)}>
          <form onSubmit={markAttendance} className="form">
            <div className="field">
              <label>Course *</label>
              <select name="course_id" required onChange={e => loadStudents(e.target.value)}>
                <option value="">— Select a course —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Student *</label>
              <select name="student_id" required>
                <option value="">— Select student —</option>
                {students.map(s => <option key={s.user_id} value={s.user_id}>{s.first_name} {s.last_name} ({s.email})</option>)}
              </select>
            </div>
            <div className="field-row">
              <Field label="Date *" name="date" type="date" defaultValue={new Date().toISOString().split("T")[0]} required />
              <div className="field">
                <label>Status *</label>
                <select name="status" required>
                  <option value="present">Present</option>
                  <option value="absent">Absent</option>
                  <option value="late">Late</option>
                  <option value="excused">Excused</option>
                </select>
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setModal(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Record Attendance</button>
            </div>
          </form>
        </Modal>
      )}

      {bulkModal && (
        <Modal title="Bulk Mark Attendance" onClose={() => setBulkModal(false)}>
          <div className="form">
            <div className="field-row">
              <div className="field">
                <label>Course *</label>
                <select value={bulkCourse} onChange={e => loadBulkStudents(e.target.value)} required>
                  <option value="">— Select a course —</option>
                  {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Date *</label>
                <input type="date" value={bulkDate} onChange={e => setBulkDate(e.target.value)} />
              </div>
            </div>

            {bulkStudents.length > 0 && (
              <>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",margin:"0.75rem 0 0.5rem"}}>
                  <span style={{fontWeight:600,fontSize:"0.9rem"}}>{bulkStudents.length} student(s)</span>
                  <button type="button" className="btn-secondary" style={{padding:"0.3rem 0.8rem",fontSize:"0.85rem"}} onClick={markAllPresent}>Mark All Present</button>
                </div>
                <div style={{maxHeight:"320px",overflowY:"auto",border:"1px solid var(--border)",borderRadius:"8px"}}>
                  <table className="att-table" style={{margin:0}}>
                    <thead><tr><th>Student</th><th>Email</th><th>Status</th></tr></thead>
                    <tbody>
                      {bulkStudents.map(s => (
                        <tr key={s.user_id}>
                          <td>{s.first_name} {s.last_name}</td>
                          <td style={{fontSize:"0.8rem",color:"var(--mid)"}}>{s.email}</td>
                          <td>
                            <select value={bulkStatuses[s.user_id] || "present"}
                              onChange={e => setBulkStatuses(p => ({ ...p, [s.user_id]: e.target.value }))}
                              style={{padding:"0.25rem 0.5rem",borderRadius:"6px",border:"1px solid var(--border)",fontSize:"0.85rem"}}>
                              <option value="present">Present</option>
                              <option value="absent">Absent</option>
                              <option value="late">Late</option>
                              <option value="excused">Excused</option>
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {bulkCourse && bulkStudents.length === 0 && (
              <p style={{color:"var(--mid)",textAlign:"center",padding:"1rem 0"}}>No enrolled students found for this course.</p>
            )}

            <div className="form-actions" style={{marginTop:"1rem"}}>
              <button type="button" className="btn-secondary" onClick={() => setBulkModal(false)}>Cancel</button>
              <button type="button" className="btn-primary" onClick={submitBulk} disabled={bulkSubmitting || bulkStudents.length === 0}>
                {bulkSubmitting ? "Saving..." : `Submit All (${bulkStudents.length})`}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// Forum / Q&A
const STOP_WORDS = new Set(['a','an','the','is','in','of','for','my','what','how','why','can','i','me','do','does','to','on','at','it','its','this','that','are','was','were','be','been','have','has','had','will','would','could','should','about','with','from','by','or','and','not','no','if','as','so','than','when','which','who','whom','whose','where','there','they','them','their','we','our','you','your','he','she','his','her']);

function findSimilarQuestions(title, existingQuestions) {
  if (!title.trim() || existingQuestions.length === 0) return [];
  const inputWords = title.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !STOP_WORDS.has(w));
  if (inputWords.length === 0) return [];
  return existingQuestions.filter(q => {
    const qWords = q.title.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !STOP_WORDS.has(w));
    const overlap = inputWords.filter(w => qWords.some(qw => qw.includes(w) || w.includes(qw)));
    return overlap.length >= Math.min(2, inputWords.length);
  });
}

function ForumView({ courses, token, user }) {
  const { t } = useLang();
  const tf = t.forum;
  const [selCourse, setSelCourse] = useState("");
  const [questions, setQuestions] = useState([]);
  const [modal, setModal]   = useState(false);
  const [detail, setDetail] = useState(null);
  const [similarQuestions, setSimilarQuestions] = useState([]);

  const loadQuestions = async (course_id) => {
    setSelCourse(course_id);
    if (!course_id) return setQuestions([]);
    const res = await authFetch(`${API}/forum/questions?course_id=${course_id}`, token);
    if (res.ok) setQuestions((await res.json()).questions || []);
  };

  const handleTitleChange = (e) => {
    setSimilarQuestions(findSimilarQuestions(e.target.value, questions));
  };

  const postQuestion = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { course_id: fd.get("course_id"), title: fd.get("title"), question_text: fd.get("question_text") };
    if (!body.course_id) return alert("Select a course!");

    const res = await authFetch(`${API}/forum/questions`, token, { method: "POST", body: JSON.stringify(body) });
    const data = await res.json();
    if (res.ok) {
      setModal(false);
      setSimilarQuestions([]);
      loadQuestions(body.course_id);
      alert("Question posted!");
    } else {
      alert("Error: " + (data.error || "Unknown"));
    }
  };

  const openSimilar = (q) => { setModal(false); setSimilarQuestions([]); setDetail(q); };

  return (
    <div>
      <div className="view-actions">
        <div className="field inline-field">
          <label>{tf.course}</label>
          <select value={selCourse} onChange={e => loadQuestions(e.target.value)}>
            <option value="">— {tf.allCourses} —</option>
            {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
          </select>
        </div>
        <button className="btn-primary" onClick={() => { setModal(true); setSimilarQuestions([]); }}>+ {tf.newQuestion}</button>
      </div>

      {!selCourse
        ? <div className="empty-state">{tf.noQuestions}</div>
        : questions.length === 0
          ? <div className="empty-state">
              <div className="empty-icon"></div>
              <p>{tf.noQuestions}</p>
              <button className="btn-primary" onClick={() => setModal(true)}>+ {tf.newQuestion}</button>
            </div>
          : <div className="questions-list">
              {questions.map(q => (
                <div key={q.question_id} className="question-card" onClick={() => setDetail(q)}>
                  <div className="q-left">
                    <h3 className="q-title">{q.title}</h3>
                    <p className="q-text">{q.question_text.slice(0, 120)}{q.question_text.length > 120 ? "…" : ""}</p>
                    <span className="q-meta">by {q.author_name} · {fmtDate(q.created_at)}</span>
                  </div>
                  <div className="q-right">
                    {!!q.is_answered ? <span className="tag success">{tf.bestAnswer}</span> : <span className="tag warning">{tf.question}</span>}
                    <span className="q-answers">{q.answer_count} {tf.answers}</span>
                  </div>
                </div>
              ))}
            </div>
      }

      {modal && (
        <Modal title={tf.newQuestion} onClose={() => { setModal(false); setSimilarQuestions([]); }}>
          <form onSubmit={postQuestion} className="form">
            <div className="field">
              <label>{tf.course} *</label>
              <select name="course_id" required onChange={e => loadQuestions(e.target.value)}>
                <option value="">— {tf.allCourses} —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
              </select>
            </div>
            <div className="field">
              <label>{tf.question} *</label>
              <input name="title" placeholder={tf.yourQuestion} required onChange={handleTitleChange} />
            </div>
            {similarQuestions.length > 0 && (
              <div style={{background:"#fffbe6",border:"1px solid #f0c040",borderRadius:"8px",padding:"0.75rem 1rem",marginBottom:"0.5rem"}}>
                <p style={{margin:"0 0 0.4rem",fontWeight:600,color:"#b45309",fontSize:"0.9rem"}}>Similar questions already exist — check before posting:</p>
                <ul style={{margin:0,paddingLeft:"1.2rem"}}>
                  {similarQuestions.map(q => (
                    <li key={q.question_id} style={{marginBottom:"0.2rem"}}>
                      <button type="button" onClick={() => openSimilar(q)}
                        style={{background:"none",border:"none",color:"#1d4ed8",cursor:"pointer",textDecoration:"underline",padding:0,fontSize:"0.88rem",textAlign:"left"}}>
                        {q.title}
                      </button>
                      <span style={{color:"#6b7280",fontSize:"0.8rem"}}> — {q.answer_count} {tf.answers}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Field label={`${tf.yourDetail} *`} name="question_text" type="textarea" placeholder={tf.yourDetail} required />
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => { setModal(false); setSimilarQuestions([]); }}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{tf.postQuestion}</button>
            </div>
          </form>
        </Modal>
      )}

      {detail && (
        <QuestionDetail question={detail} token={token} user={user} onClose={() => { setDetail(null); loadQuestions(selCourse); }} />
      )}
    </div>
  );
}

function QuestionDetail({ question, token, user, onClose }) {
  const { t } = useLang();
  const tf = t.forum;
  const [full, setFull]     = useState(null);
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    authFetch(`${API}/forum/questions/${question.question_id}`, token)
      .then(r => r.json()).then(d => setFull(d));
  }, [question.question_id, token]);

  const postAnswer = async () => {
    if (!answer.trim()) return alert("Please write an answer!");
    const res = await authFetch(`${API}/forum/questions/${question.question_id}/answers`, token, {
      method: "POST", body: JSON.stringify({ answer_text: answer }),
    });
    const data = await res.json();
    if (res.ok) {
      setAnswer("");
      authFetch(`${API}/forum/questions/${question.question_id}`, token)
        .then(r => r.json()).then(d => setFull(d));
      alert("Answer posted!");
    } else {
      alert("Error: " + (data.error || "Unknown"));
    }
  };

  if (!full) return <Modal title="Loading…" onClose={onClose}><p>Loading…</p></Modal>;

  return (
    <Modal title={full.question.title} onClose={onClose} wide>
      <div className="qdetail">
        <div className="qdetail-body">
          <p>{full.question.question_text}</p>
          <span className="q-meta">by {full.question.author_name} · {fmtDate(full.question.created_at)}</span>
        </div>

        <h4 className="answers-head">{full.answers.length} {tf.answers}</h4>
        {full.answers.length === 0
          ? <p className="empty-msg">{tf.noQuestions}</p>
          : full.answers.map(a => (
            <div key={a.answer_id} className={`answer-card ${!!a.is_accepted ? "accepted" : ""}`}>
              {!!a.is_accepted && <div className="accepted-badge">{tf.bestAnswer}</div>}
              <div className="answer-card-body">
                <div className="answer-card-main">
                  <p>{a.answer_text}</p>
                  <span className="q-meta">{a.author_name} ({a.role}) · {fmtDate(a.created_at)}</span>
                </div>
                {(user.role === 'professor' || user.user_id === full.question.asked_by) && a.is_accepted !== 1 && (
                  <button className="accept-btn" onClick={async () => {
                    await authFetch(`${API}/forum/answers/${a.answer_id}/accept`, token, { method: 'POST' });
                    authFetch(`${API}/forum/questions/${question.question_id}?track=0`, token)
                      .then(r => r.json()).then(d => setFull(d));
                  }}>✓ Best Answer</button>
                )}
              </div>
            </div>
          ))
        }

        <div className="answer-write">
          <h4>{tf.yourAnswer}</h4>
          <textarea className="submit-notes" rows={5} placeholder={tf.yourAnswer}
            value={answer} onChange={e => setAnswer(e.target.value)} />
          <button className="btn-primary" onClick={postAnswer}>{tf.postAnswer}</button>
        </div>
      </div>
    </Modal>
  );
}

// announcements
function AnnouncementsView({ isProf, courses, announcements, token, reload }) {
  const { t } = useLang();
  const tan = t.announcements;
  const [modal, setModal] = useState(false);

  const create = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { course_id: fd.get("course_id"), title: fd.get("title"), content: fd.get("content"), priority: fd.get("priority") };
    if (!body.course_id) return alert("Select a course!");
    const res = await authFetch(`${API}/announcements`, token, { method: "POST", body: JSON.stringify(body) });
    const data = await res.json();
    if (res.ok) { setModal(false); reload(); alert("Announcement posted!"); }
    else alert("Error: " + (data.error || "Unknown"));
  };

  const priorityColor = { low: "info", normal: "info", high: "warning", urgent: "danger" };

  return (
    <div>
      {isProf && (
        <div className="view-actions">
          <button className="btn-primary" onClick={() => setModal(true)}>+ {tan.new}</button>
        </div>
      )}

      {announcements.length === 0
        ? <div className="empty-state">
            <div className="empty-icon"></div>
            <p>{tan.none}</p>
            {isProf && <button className="btn-primary" onClick={() => setModal(true)}>{tan.post}</button>}
          </div>
        : <div className="announcements-list">
            {announcements.map(a => (
              <div key={a.announcement_id} className="announcement-card">
                <div className="ann-header">
                  <h3>{a.title}</h3>
                  <div className="ann-tags">
                    <span className={`tag ${priorityColor[a.priority] || "info"}`}>{a.priority}</span>
                    {a.course_name && <span className="tag">{a.course_name}</span>}
                  </div>
                </div>
                <p className="ann-content">{a.content}</p>
                <span className="row-meta">by {a.author_name} · {fmtDate(a.created_at)}</span>
              </div>
            ))}
          </div>
      }

      {modal && (
        <Modal title={tan.new} onClose={() => setModal(false)}>
          <form onSubmit={create} className="form">
            <div className="field">
              <label>{tan.course} *</label>
              <select name="course_id" required>
                <option value="">— {t.common.all} —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
              </select>
            </div>
            <Field label={`${tan.title} *`} name="title" placeholder={tan.title} required />
            <Field label={`${tan.message} *`} name="content" type="textarea" placeholder={tan.message} required />
            <div className="field">
              <label>Priority</label>
              <select name="priority">
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setModal(false)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary">{tan.post}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, onClose, children, wide }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={`modal-box ${wide ? "modal-wide" : ""}`} onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, name, type = "text", placeholder, required, defaultValue, min, max }) {
  return (
    <div className="field">
      <label>{label}</label>
      {type === "textarea"
        ? <textarea name={name} placeholder={placeholder} rows={4} required={required} defaultValue={defaultValue} />
        : <input name={name} type={type} placeholder={placeholder} required={required} defaultValue={defaultValue} min={min} max={max} />
      }
    </div>
  );
}

// AI Insights
function AIInsightsView({ isProf, token, user, setChatInput, setChatOpen }) {
  const { t, lang } = useLang();
  const tai = t.ai;
  const [report, setReport]   = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchReport = async () => {
    setLoading(true);
    setReport(null);
    try {
      const endpoint = isProf ? `${API}/ai/professor-insights?lang=${lang}` : `${API}/ai/student-report?lang=${lang}`;
      const res  = await authFetch(endpoint, token);
      const data = await res.json();
      setReport(data);
    } catch (e) {
      setReport({ narrative: "Failed to generate report. Check your OpenAI API key.", workload: null });
    } finally {
      setLoading(false);
    }
  };

const renderNarrative = (text) => {
  if (!text) return null;
  return text.split("\n").filter(l => l.trim()).map((line, i) => {
    const trimmed = line.trim();
    // full line is a header: **Title**
    const fullHeader = trimmed.match(/^\*\*(.+?)\*\*$/);
    if (fullHeader) return <h4 key={i} className="report-section-header">{fullHeader[1]}</h4>;
    // line starts with bold: **Title** some text...
    const inlineHeader = trimmed.match(/^\*\*(.+?)\*\*\s+(.+)/);
    if (inlineHeader) return (
      <p key={i} className="report-paragraph">
        <span className="report-section-header" style={{display:'block', marginBottom:'4px'}}>{inlineHeader[1]}</span>
        {inlineHeader[2]}
      </p>
    );
    // strip any remaining stray asterisks
    return <p key={i} className="report-paragraph">{trimmed.replace(/\*\*/g, '')}</p>;
  });
};

  const askFollowUp = (q) => { setChatInput(q); setChatOpen(true); };

  const profFollowUps   = tai.profFollowUps;
  const studentFollowUps = tai.studentFollowUps;

  const priorityColors = { urgent: "danger", high: "warning", medium: "info", low: "success" };

  return (
    <div className="insights-page">
      <div className="insights-hero">
        <div className="insights-hero-text">
          <h2>{isProf ? tai.heroProfTitle : tai.heroStudentTitle}</h2>
          <p>{isProf ? tai.heroProfDesc : tai.heroStudentDesc}</p>
        </div>
        <button className="btn-primary insights-btn" onClick={fetchReport} disabled={loading}>
          {loading ? tai.generating : report ? tai.generate : tai.generate}
        </button>
      </div>

      {loading && (
        <div className="insights-loading">
          <div className="insights-spinner" />
          <p>{tai.typing}</p>
        </div>
      )}

      {report && !loading && (
        <div className="insights-grid">

          {/* Main narrative card */}
          <div className="insights-card insights-main">
            <div className="insights-card-head">
              <span className="insights-icon">{isProf ? "📋" : "🎓"}</span>
              <h3>{isProf ? tai.reportProfTitle : tai.reportStudentTitle}</h3>
              <span className="insights-badge">{tai.liveData}</span>
            </div>
            <div className="report-body">
              {renderNarrative(report.narrative)}
            </div>
          </div>

          {/* Workload priority card — students only */}
          {!isProf && report.workload?.schedule?.length > 0 && (
            <div className="insights-card insights-workload">
              <div className="insights-card-head">
                <span className="insights-icon">📌</span>
                <h3>{tai.priorityList}</h3>
                <span className="insights-badge">{n(report.workload.workload_analysis.total_assignments, lang)} {tai.pending}</span>
              </div>
              <div className="workload-list">
                {report.workload.schedule.slice(0, 6).map((item, i) => {
                  const daysLabel = item.days_until_due < 0 ? tai.overdue
                    : item.days_until_due === 0 ? tai.dueToday
                    : tai.daysLeft(n(item.days_until_due, lang));
                  return (
                    <div key={i} className={`workload-item`}>
                      <div className="workload-rank">#{i + 1}</div>
                      <div className="workload-info">
                        <div className="workload-title">{item.title}</div>
                        <div className="workload-meta">{item.course} · {daysLabel} · {n(item.points, lang)} {tai.pts}</div>
                      </div>
                      <span className={`tag ${priorityColors[item.priority] || "info"}`}>{tai.priorityLabels[item.priority] || item.priority}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Follow-up questions card */}
          <div className="insights-card insights-followup">
            <div className="insights-card-head">
              <span className="insights-icon">💬</span>
              <h3>{tai.askAI}</h3>
            </div>
            <p className="insights-hint">{tai.conversationHint}</p>
            <div className="followup-list">
              {(isProf ? profFollowUps : studentFollowUps).map(q => (
                <button key={q} className="followup-btn" onClick={() => askFollowUp(q)}>
                  <span className="followup-arrow">›</span> {q}
                </button>
              ))}
            </div>
          </div>

        </div>
      )}

      {!report && !loading && (
        <div className="insights-empty">
          <div className="insights-empty-icon">{isProf ? "📊" : "📖"}</div>
          <p>{isProf ? tai.emptyProf : tai.emptyStudent}</p>
        </div>
      )}
    </div>
  );
}

// SubmissionCard
function SubmissionCard({ submission: s, assignment: a, token, onGraded }) {
  const { t } = useLang();
  const tg = t.grades;
  const ta = t.assignments;
  const [expanded, setExpanded] = useState(false);
  const [grading, setGrading]   = useState(false);
  const [score, setScore]       = useState(s.score ?? "");
  const [feedback, setFeedback] = useState(s.feedback ?? "");
  const [saving, setSaving]     = useState(false);

  const submitGrade = async () => {
    if (score === "" || isNaN(Number(score))) return alert("Enter a valid score");
    const pts = Number(score);
    if (pts < 0 || pts > a.points) return alert(`Score must be 0–${a.points}`);
    setSaving(true);
    const res = await authFetch(`${API}/assignments/${a.assignment_id}/grade`, token, {
      method: "POST",
      body: JSON.stringify({ student_id: s.student_id, score: pts, feedback }),
    });
    setSaving(false);
    if (res.ok) { setGrading(false); onGraded(); }
    else alert("Failed to save grade");
  };

  return (
    <div className={`sub-card ${expanded ? "expanded" : ""}`}>
      <div className="sub-card-head" onClick={() => setExpanded(p => !p)}>
        <div className="sub-student">
          <div className="sub-avatar">{s.first_name[0]}{s.last_name[0]}</div>
          <div>
            <div className="sub-name">{s.first_name} {s.last_name}</div>
            <div className="sub-email">{s.email}</div>
          </div>
        </div>
        <div className="sub-meta">
          <span className="sub-date">{fmtTime(s.submitted_at)}</span>
          <span className={`tag ${s.status === "graded" ? "success" : "info"}`}>{s.status}</span>
          {s.score !== null && <span className="tag success">{s.score}/{a.points}</span>}
          <span className="sub-chevron">{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {expanded && (
        <div className="sub-body">
          <div className="sub-content-box">
            <label className="sub-content-label">{ta.submitted}</label>
            <div className="sub-content-text">
              {s.file_path && s.file_path.includes('.') ? (
                <button className="btn-secondary" style={{fontSize:".82rem",padding:".25rem .75rem"}}
                  onClick={() => authFetch(`${API}/submissions/${s.submission_id}/file`, token)
                    .then(r => r.ok ? r.blob() : null)
                    .then(blob => { if (!blob) return alert("File not found"); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href=url; a.download=s.file_path; a.click(); URL.revokeObjectURL(url); })}>
                  {t.common.download}
                </button>
              ) : s.file_path && s.file_path.trim() ? (
                <span>{s.file_path}</span>
              ) : (
                <span className="no-content">{ta.notSubmitted}</span>
              )}
            </div>
          </div>

          {s.feedback && (
            <div className="sub-content-box">
              <label className="sub-content-label">{ta.feedback}</label>
              <div className="sub-content-text">{s.feedback}</div>
            </div>
          )}

          {!grading && (
            <button className="btn-primary sub-grade-btn" onClick={() => setGrading(true)}>
              {s.status === "graded" ? tg.editGrade : tg.gradeBtn}
            </button>
          )}

          {grading && (
            <div className="grade-form">
              <h5>{tg.gradeBtn} — max {a.points} {ta.points}</h5>
              <div className="grade-inputs">
                <div className="field">
                  <label>{tg.score} (0 – {a.points})</label>
                  <input type="number" min="0" max={a.points} value={score}
                    onChange={e => setScore(e.target.value)} placeholder={`0–${a.points}`} />
                </div>
                <div className="field" style={{flex:2}}>
                  <label>{ta.feedback}</label>
                  <textarea rows={3} value={feedback} onChange={e => setFeedback(e.target.value)}
                    placeholder={ta.professorFeedback} />
                </div>
              </div>
              <div className="grade-actions">
                <button className="btn-secondary" onClick={() => setGrading(false)}>{t.common.cancel}</button>
                <button className="btn-primary" onClick={submitGrade} disabled={saving}>
                  {saving ? t.common.loading : tg.saveGrade}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Resources
function ResourcesView({ isProf, courses, token, reload }) {
  const { t } = useLang();
  const tr = t.resources;
  const [resources, setResources] = useState([]);
  const [modal, setModal] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const loadResources = async () => {
    const res = await authFetch(`${API}/resources`, token);
    const data = await res.json();
    setResources(data.resources || []);
  };

  useEffect(() => { if (token) loadResources(); }, [token]);

  const uploadResource = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (!fd.get("file") || !fd.get("file").name) return alert("Please select a file");
    setIsUploading(true);
    try {
      const res = await fetch(`${API}/resources`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd  // send as multipart/form-data (no JSON)
      });
      const data = await res.json();
      if (res.ok) {
        setModal(false);
        loadResources();
        alert("Resource uploaded!");
      } else {
        alert(data.error || "Upload failed");
      }
    } catch (e) {
      alert("Upload error: " + e.message);
    }
    setIsUploading(false);
  };

  const downloadFile = (r) => {
    fetch(`${API}/resources/${r.resource_id}/download`, {
      headers: { Authorization: `Bearer ${token}` }
    }).then(res => res.blob()).then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.title}.${r.file_type}`;
      a.click();
      URL.revokeObjectURL(url);
    }).catch(() => alert("Download failed"));
  };

  return (
    <div className="view-container">
      {isProf && (
        <div className="view-header">
          <button className="btn-primary" onClick={() => setModal(true)}>+ {tr.upload}</button>
        </div>
      )}

      {resources.length === 0 ? (
        <div className="empty-state">
          <p>{tr.none}</p>
          {isProf && <button className="btn-primary" onClick={() => setModal(true)}>{tr.upload}</button>}
        </div>
      ) : (
        <div className="resources-grid">
          {resources.map(r => (
            <div key={r.resource_id} className="resource-card">
              <div className="resource-type-badge">
                {(r.file_type || 'FILE').toUpperCase()}
              </div>
              <h3 className="resource-title">{r.title}</h3>
              <p className="resource-desc">{r.description || t.common.noData}</p>
              <div className="resource-meta">
                <span className="resource-course">{r.course_name || ""}</span>
                <span className="resource-downloads">{r.downloads} {tr.download}</span>
              </div>
              <button className="btn-secondary btn-block" onClick={() => downloadFile(r)}>
                {tr.download}
              </button>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <Modal title={tr.upload} onClose={() => setModal(false)}>
          <form onSubmit={uploadResource} className="form">
            <div className="field">
              <label>{tr.course} *</label>
              <select name="course_id" required>
                <option value="">— {tr.allCourses} —</option>
                {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
              </select>
            </div>
            <Field label={`${tr.title} *`} name="title" placeholder="e.g., Lecture 1 Slides" required />
            <Field label={t.assignments.descLabel} name="description" placeholder="Brief description of the resource" />
            <div className="field">
              <label>{tr.file} *</label>
              <input type="file" name="file" required
                     accept=".pdf,.pptx,.docx,.xlsx,.txt,.png,.jpg,.zip" />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setModal(false)}>{t.common.cancel}</button>
              <button type="submit" className="btn-primary" disabled={isUploading}>
                {isUploading ? t.common.loading : tr.upload}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

// Profile
function ProfileView({ token, user, isProf, courses, onUserUpdate }) {
  const { t } = useLang();
  const tp = t.profile;
  const [profile, setProfile]   = useState(null);
  const [editing, setEditing]   = useState(false);
  const [saving, setSaving]     = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName,  setLastName]  = useState("");
  const [phone,     setPhone]     = useState("");
  const avatarRef = useRef(null);

  const load = () =>
    authFetch(`${API}/profile`, token)
      .then(r => r.json())
      .then(data => {
        setProfile(data);
        setFirstName(data.first_name);
        setLastName(data.last_name);
        setPhone(data.phone === "Not provided" ? "" : data.phone || "");
      });

  useEffect(() => { load(); }, [token]);

  const saveProfile = async () => {
    setSaving(true);
    const res = await authFetch(`${API}/profile`, token, {
      method: "PUT",
      body: JSON.stringify({ first_name: firstName, last_name: lastName, phone }),
    });
    const data = await res.json();
    if (res.ok && onUserUpdate) onUserUpdate(data.user);
    await load();
    setSaving(false);
    setEditing(false);
  };

  const uploadAvatar = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("avatar", file);
    const res = await fetch(`${API}/users/avatar`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    const data = await res.json();
    if (res.ok) {
      if (onUserUpdate) onUserUpdate({ ...user, profile_picture: data.profile_picture });
      await load();
    }
  };

  if (!profile) return <div className="loading-state">{t.common.loading}</div>;

  const profileUser = { ...user, profile_picture: profile.profile_picture };

  return (
    <div className="profile-page">

      {/* Header banner */}
      <div className="profile-header-card">
        {/* Avatar with change-photo overlay */}
        <div className="profile-avatar-wrap">
          <UserAvatar user={profileUser} size={90} className="profile-avatar-img" />
          <button
            className="profile-avatar-change"
            onClick={() => avatarRef.current?.click()}
            title={tp.changePhoto}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/>
            </svg>
          </button>
          <input ref={avatarRef} type="file" accept=".jpg,.jpeg,.png,.webp" style={{display:"none"}}
            onChange={e => uploadAvatar(e.target.files[0])} />
        </div>

        {editing ? (
          <div className="profile-edit-name">
            <input className="profile-name-input" value={firstName} onChange={e => setFirstName(e.target.value)} placeholder={tp.firstName} />
            <input className="profile-name-input" value={lastName}  onChange={e => setLastName(e.target.value)}  placeholder={tp.lastName}  />
          </div>
        ) : (
          <h2 className="profile-full-name">{profile.first_name} {profile.last_name}</h2>
        )}

        <span className="tag profile-role-tag" style={{textTransform:"capitalize"}}>
          {profile.role === "professor" ? t.roles.professor : t.roles.student}
        </span>
        <p className="profile-since">{tp.memberSince} {fmtDate(profile.created_at)}</p>

        <div className="profile-header-actions">
          {editing ? (
            <>
              <button className="btn-primary" onClick={saveProfile} disabled={saving}>
                {saving ? tp.removing : tp.save}
              </button>
              <button className="btn-secondary" onClick={() => { setEditing(false); setFirstName(profile.first_name); setLastName(profile.last_name); setPhone(profile.phone === "Not provided" ? "" : profile.phone || ""); }}>
                {t.common.cancel}
              </button>
            </>
          ) : (
            <button className="btn-secondary" onClick={() => setEditing(true)}>{tp.edit}</button>
          )}
        </div>
      </div>

      {/* Info grid */}
      <div className="profile-grid">
        <div className="profile-info-card">
          <div className="profile-info-label">{tp.email}</div>
          <div className="profile-info-value">{profile.email}</div>
        </div>

        <div className="profile-info-card">
          <div className="profile-info-label">{tp.phone}</div>
          {editing ? (
            <input className="profile-inline-input" value={phone} onChange={e => setPhone(e.target.value)} placeholder="e.g. 01012345678" />
          ) : (
            <div className="profile-info-value">{profile.phone || "—"}</div>
          )}
        </div>

        <div className="profile-info-card">
          <div className="profile-info-label">{tp.faculty}</div>
          <div className="profile-info-value">Academia Platform</div>
        </div>

        <div className="profile-info-card">
          <div className="profile-info-label">{isProf ? t.courses.myCourses : t.courses.enrolled}</div>
          <div className="profile-stat-val">
            {isProf
              ? (profile.courses_teaching_count ?? courses.length ?? "—")
              : (profile.enrolled_courses_count ?? "—")}
          </div>
          <div className="profile-stat-sub">{isProf ? t.courses.myCourses : t.courses.enrolled}</div>
        </div>
      </div>

    </div>
  );
}

// Analytics
function GradesView({ courses, token }) {
  const { t } = useLang();
  const tg = t.grades;
  const [grades, setGrades] = useState([]);
  const [courseFilter, setCourseFilter] = useState("");

  useEffect(() => {
    const url = courseFilter ? `${API}/grades?course_id=${courseFilter}` : `${API}/grades`;
    authFetch(url, token).then(r => r.json()).then(d => setGrades(d.grades || []));
  }, [token, courseFilter]);

  const pct = (score, max) => max > 0 ? Math.round(score / max * 100) : 0;
  const pctColor = (p) => p >= 80 ? "success" : p >= 60 ? "warning" : "danger";

  return (
    <div>
      <div className="view-actions">
        <select className="filter-select" value={courseFilter} onChange={e => setCourseFilter(e.target.value)}>
          <option value="">{tg.allCourses}</option>
          {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_name}</option>)}
        </select>
      </div>

      {grades.length === 0
        ? <div className="empty-state">{tg.none}</div>
        : (
          <div className="grades-table-wrap">
            <table className="grades-table">
              <thead>
                <tr>
                  <th>{tg.student}</th>
                  <th>{tg.type}</th>
                  <th>{tg.assignment}</th>
                  <th>{tg.course}</th>
                  <th>{tg.score}</th>
                  <th>{tg.date}</th>
                </tr>
              </thead>
              <tbody>
                {grades.map((g, i) => {
                  const p = pct(g.score, g.max_score);
                  const isQuiz = g.entry_type === "quiz";
                  return (
                    <tr key={g.grade_id || i}>
                      <td>
                        <div className="grade-student-name">{g.student_name}</div>
                        <div className="grade-student-email">{g.student_email}</div>
                      </td>
                      <td>
                        <span className={`tag ${isQuiz ? "warning" : "info"}`} style={{fontSize:"0.75rem"}}>
                          {isQuiz ? tg.quiz : tg.assignment_type}
                        </span>
                      </td>
                      <td>{isQuiz ? g.quiz_title : g.assignment_title}</td>
                      <td><span className="tag info">{g.course_name}</span></td>
                      <td>
                        <span className={`tag ${pctColor(p)}`}>{g.score}/{g.max_score}</span>
                        <span className="grade-pct-small">{p}%</span>
                      </td>
                      <td className="grade-date">{fmtDate(g.graded_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  );
}

function AnalyticsView({ isProf, token }) {
  const { t, lang } = useLang();
  const tana = t.analytics;
  const [data, setData] = useState(null);

  useEffect(() => {
    const url = isProf ? `${API}/analytics/professor` : `${API}/analytics/student`;
    authFetch(url, token).then(r => r.json()).then(setData);
  }, [token, isProf]);

  if (!data) return <div className="loading-state">{t.common.loading}</div>;

  return (
    <div className="analytics-page">
      <div className="analytics-header">
        <h2>{tana.overview}</h2>
      </div>
      
      {!isProf ? (
        // Student Analytics
        <div className="analytics-grid">
          <div className="analytics-card">
            <h3>{tana.avgAttendance}</h3>
            <div className={`big-stat ${data.current_attendance_rate >= 75 ? 'stat-ok' : 'stat-warn'}`}>
              {data.current_attendance_rate}%
            </div>
            <p className={`status-badge ${data.attendance_status}`}>
              {data.attendance_status}
            </p>
          </div>

          <div className="analytics-card">
            <h3>{tana.submissionRate}</h3>
            <div className={`big-stat ${data.submission_rate >= 80 ? 'stat-ok' : 'stat-warn'}`}>
              {data.submission_rate}%
            </div>
            <p className="stat-meta">{data.assignments_completed} · {data.assignments_overdue}</p>
          </div>

          <div className="analytics-card">
            <h3>{tana.engagementScore}</h3>
            <div className="big-stat stat-sec">{n(data.engagement_score, lang)}%</div>
            <p className="stat-meta">{n(data.forum_posts, lang)} {tana.forumPosts}</p>
          </div>

          {data.risk_factors && data.risk_factors.length > 0 && (
            <div className="analytics-card wide alert-card-warn">
              <h3>{tana.riskFactors}</h3>
              <ul className="risk-list">
                {data.risk_factors.map((risk, i) => (
                  <li key={i} className="risk-item">
                    <span className="risk-icon"></span>
                    <div className="risk-content">
                      <strong>{risk.title}</strong>
                      <p>{risk.description}</p>
                      <span className="risk-action">{risk.recommendation}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        // Professor Analytics
        <div className="analytics-grid">
          <div className="analytics-card wide alert-card-warn">
            <h3>{tana.requireAttention}</h3>
            <div className="risk-summary-grid">
              <div className="risk-stat">
                <div className="risk-stat-num stat-danger">{n(data.high_risk_students, lang)}</div>
                <div className="risk-stat-label">{tana.highRisk}</div>
              </div>
              <div className="risk-stat">
                <div className="risk-stat-num stat-warn">{n(data.medium_risk_students, lang)}</div>
                <div className="risk-stat-label">{tana.mediumRisk}</div>
              </div>
              <div className="risk-stat">
                <div className="risk-stat-num stat-ok">{n(data.low_risk_students, lang)}</div>
                <div className="risk-stat-label">{tana.onTrack}</div>
              </div>
            </div>
          </div>

          {data.at_risk_students && data.at_risk_students.length > 0 && (
            <>
              <div className="section-heading-row">
                <h3 className="section-heading">{tana.highRiskStudents}</h3>
              </div>
              {data.at_risk_students.slice(0, 6).map((s, i) => (
                <div key={i} className="analytics-card">
                  <span className="tag danger" style={{marginBottom:"0.5rem",display:"inline-block"}}>{tana.highRisk}</span>
                  <h3 className="student-name">{s.name}</h3>
                  <p className="student-email">{s.email}</p>
                  <p className="student-email" style={{color:"var(--mid)"}}>{s.course}</p>
                  <div className="student-metrics">
                    <span className="metric metric-warn">{n(s.attendance, lang)}% {tana.attendance}</span>
                  </div>
                  <p style={{fontSize:"0.8rem",color:"var(--danger)",margin:"0.4rem 0 0.6rem"}}>{s.reason}</p>
                  <button className="btn-secondary btn-sm" onClick={() => alert(`Contact: ${s.email}`)}>
                    {tana.contactStudent}
                  </button>
                </div>
              ))}
            </>
          )}

          {data.medium_risk_students_list && data.medium_risk_students_list.length > 0 && (
            <>
              <div className="section-heading-row">
                <h3 className="section-heading">{tana.mediumRiskStudents}</h3>
              </div>
              {data.medium_risk_students_list.slice(0, 6).map((s, i) => (
                <div key={i} className="analytics-card">
                  <span className="tag warning" style={{marginBottom:"0.5rem",display:"inline-block"}}>{tana.mediumRisk}</span>
                  <h3 className="student-name">{s.name}</h3>
                  <p className="student-email">{s.email}</p>
                  <p className="student-email" style={{color:"var(--mid)"}}>{s.course}</p>
                  <div className="student-metrics">
                    <span className="metric metric-warn">{n(s.attendance, lang)}% {tana.attendance}</span>
                  </div>
                  <p style={{fontSize:"0.8rem",color:"var(--warn)",margin:"0.4rem 0 0.6rem"}}>{s.reason}</p>
                  <button className="btn-secondary btn-sm" onClick={() => alert(`Contact: ${s.email}`)}>
                    {tana.contactStudent}
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
