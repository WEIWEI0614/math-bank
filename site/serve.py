#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serve.py —— 练习站的本地服务（把作答写进 bank.sqlite）

为什么需要它：静态页只能把数据存在浏览器 localStorage，换台设备就丢。
这个服务跑在老师自己的电脑上，数据落在本地 SQLite，**不上传任何云端**，
满足「学生数据（姓名+成绩）本地留存」的要求。

用法:
    python3 site/serve.py            # 然后打开 http://127.0.0.1:8770
    python3 site/serve.py --port 9000

接口（2026-09-25 v2：登录鉴权 + 角色隔离）:
    POST /api/login    {role:"teacher",pass} | {role:"student",name,pass}
                                            -> {token,role,name}（Bearer token，TTL 7 天）
    POST /api/logout                                             注销当前 token
    GET  /api/me                                                 当前会话身份（前端恢复登录态）
    POST /api/attempt  {qid,topic,score,secs,why,err}            记录作答【需学生 token】
    GET  /api/students                                           学生清单与统计【需教师 token】
    GET  /api/export[?name=张三]                                 导出（学生仅自己，教师全员）【需 token】
    GET  /api/quiz?name=&unit=&n=                                专项练习 HTML【需教师 token】
    GET  /api/sync?since=<ISO8601>                               增量作答（镜像守护用）【需教师 token】
零 LLM 调用。只监听 127.0.0.1。

== 安全防护（2026-09-25，应「建立网站安全防护机制」要求）==
  1. Host 白名单      只接受 127.0.0.1 / localhost / ::1 —— 防 DNS-rebinding
                      （本机浏览器被诱导访问恶意域名解析到 127.0.0.1 的场景）
  2. 静态文件黑名单    拒绝 .py / .sqlite / .db / .env 与任何含 '..' 的路径 ——
                      防 serve.py 源码与数据库外泄（http.server 本身已归一化
                      路径，这里是纵深防御）
  3. 安全响应头       X-Content-Type-Options: nosniff / X-Frame-Options /
                      Referrer-Policy / Content-Security-Policy（限 cdnjs KaTeX）
  4. 同源写入校验     POST 带 Origin/Referer 时必须来自本机 —— 防跨站伪造作答
  5. 请求限流         每客户端 IP 120 次/分钟（内存令牌窗），超限 429
  6. 输入校验         请求体 ≤64KB；name/qid/topic/score/secs/n 全部白名单化
                      与范围钳制；quiz 的 n 钳到 1..50
  7. 版本隐匿         Server 头不暴露 Python 版本
"""
import json, os, sqlite3, sys, argparse, time, uuid, urllib.parse, re, threading, mimetypes, secrets
from collections import deque
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

mimetypes.add_type("image/webp", ".webp")   # 旧 Python mimetypes 不认 webp

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(ROOT)
DB   = os.path.join(BASE, "bank.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS student (
  sid TEXT PRIMARY KEY, name TEXT, cohort TEXT, target_units TEXT, goal TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS attempt (
  aid TEXT PRIMARY KEY, sid TEXT NOT NULL, qid TEXT NOT NULL, ts TEXT NOT NULL,
  resp_raw TEXT, self_report TEXT, score REAL, score_max REAL, rubric_hits TEXT,
  grader TEXT, err_type TEXT, secs INTEGER, is_retry INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_a_sid ON attempt(sid, ts);
"""
SECS_SLOW, CREDIT_SLOW = 120, 0.7
INIT, K_HI, K_LO = 1000.0, 32.0, 12.0
MIN_T, SHOW_AT = 3, 15

# ---------- 安全参数 ----------
DENIED_EXT = (".py", ".pyc", ".sqlite", ".sqlite3", ".db", ".env", ".bak")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 64 * 1024                 # POST 体上限 64KB
RL_WINDOW, RL_MAX = 60.0, 120        # 每 IP 120 次/分钟
QID_RE   = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TOPIC_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
ERR_SET  = {"concept", "procedure", "setup", "algebra", "calc", "time", "misread"}
CSP = ("default-src 'self'; "
       "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
       "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
       "img-src 'self' data:; "
       "font-src 'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
       "connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'self'")

_RL = {}          # ip -> deque[timestamp]
_RL_LOCK = threading.Lock()

# ---------- 云发布模式（WorkBuddy 站点）----------
# 平台注入 PORT 环境变量即视为云模式：绑 0.0.0.0、Host/Origin 校验
# 从「仅本机」放宽为「同源」、限流放宽（反代共享入口 IP）。
# 本机运行（无 PORT）时所有行为与原版完全一致。
CLOUD = bool(os.environ.get("PORT"))
if CLOUD:
    RL_MAX = 600                     # 反代后 client IP 共享，放宽到 600/min


def rate_ok(ip):
    now = time.time()
    with _RL_LOCK:
        dq = _RL.setdefault(ip, deque())
        while dq and now - dq[0] > RL_WINDOW:
            dq.popleft()
        if len(dq) >= RL_MAX:
            return False
        dq.append(now)
        return True


def db():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    return con

# ---------- 登录口令与会话（v2 角色隔离）----------
def _load_secret(path, env, default):
    """口令来源优先级：环境变量 > 本地密钥文件 > 首次生成的默认值。
    密钥文件落 BASE（bank.sqlite 同级），随项目走、不进发布包（发布包只拷 site/）。"""
    v = os.environ.get(env)
    if v:
        return v.strip()
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    v = default
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(v)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return v

TEACHER_KEY = _load_secret(os.path.join(BASE, ".teacher_key"), "TEACHER_KEY", "shuxue2026")
STUDENT_CODE = _load_secret(os.path.join(BASE, ".student_code"), "STUDENT_CODE", "banji2026")

SESSIONS = {}                 # token -> {role,name,sid,exp}
SESS_TTL = 7 * 24 * 3600
_SESS_LOCK = threading.Lock()


def session_new(role, name, sid=None):
    tok = secrets.token_urlsafe(24)
    now = time.time()
    with _SESS_LOCK:
        for k in [k for k, v in SESSIONS.items() if v["exp"] < now]:
            del SESSIONS[k]
        SESSIONS[tok] = {"role": role, "name": name, "sid": sid, "exp": now + SESS_TTL}
    return tok


def session_get(req):
    """从请求头取会话；无/过期返回 None。"""
    auth = req.headers.get("Authorization") or ""
    tok = auth[7:] if auth.startswith("Bearer ") else ""
    if not tok:
        tok = (req._q().get("token") or [""])[0]   # GET 也允许 ?token=（导出链接场景）
    if not tok:
        return None
    with _SESS_LOCK:
        s = SESSIONS.get(tok)
        if s and s["exp"] < time.time():
            del SESSIONS[tok]
            s = None
        return s


def session_drop(req):
    auth = req.headers.get("Authorization") or ""
    tok = auth[7:] if auth.startswith("Bearer ") else ""
    with _SESS_LOCK:
        SESSIONS.pop(tok, None)


def get_sid(con, name):
    r = con.execute("SELECT sid FROM student WHERE name=?", (name,)).fetchone()
    if r: return r[0]
    sid = "S-" + uuid.uuid4().hex[:10]
    con.execute("INSERT INTO student (sid,name,created_at) VALUES (?,?,datetime('now'))", (sid, name))
    con.commit()
    return sid

def get_sid_or_none(con, name):
    """只读查找：命中不到返回 None，**绝不建号**。

    get_sid()带 INSERT 副作用，早前被 /api/quiz、/api/export 这类 GET 接口
    当作只读查询复用，导致教师拼错一次姓名就把幽灵学生永久写进花名册
    （GET 还绕过了 POST 才有的同源校验）。建号只应发生在真正需要它的
    /api/login 与 /api/attempt 上。
    """
    r = con.execute("SELECT sid FROM student WHERE name=?", (name,)).fetchone()
    return r[0] if r else None


# 题干/判分细则常粘着版权声明（原卷 OCR 带进来的），出卷时必须裁掉：
# 让学生看到 UCLES/Cambridge 的版权页不合适，也会把整张卷子的文字撑脏。
# 两种位置都存在：stem_md 多在尾部，ms_md 多在开头（"© UCLES 2022\nPage 6 of 20\n\n1..."）。
# 题干尾部常粘着整段版权/出版声明（原卷 OCR 带进来的），出卷时必须裁掉：
# 让学生看到 UCLES/Cambridge 的版权页、以及 www.OnlineExamHelp.com 这类
# 第三方试卷站水印都不合适，也会把整张卷子的文字撑脏。
#
# 关键：绝大多数版权尾巴是**与正文同行**的（实测 321 道含
# "Permission to reproduce" 的题里320 道同行），所以不能要求
# 版权特征独占一行 —— 那样规则对 99.7% 的真实情况失效。
# 改为：从「版权特征短语首次出现的位置」截断到文末。
_PAPER_TAIL_CUES = [
    "Permission to reproduce",
    "Items where third-party",
    "Photocopiable",
    "Additional Page",
    "Do not write in this margin",
    "UCLES ",
    "University of Cambridge International Examinations is part of",
    "CambridgeAssessment is the brand name",
    "wishes to thank the following",
]
# 第三方试卷站水印：整行或行内出现都清掉。
# 域名后面常紧跟孤立页码（如 "www.OnlineExamHelp.com 3"），所以不能要求
# 其后必须是换行，否则会漏掉这一类（实测残留 12 条全是这种形态）。
_PAPER_WATERMARK = re.compile(
    r"(?:\n|\s)*(?:www\.)?[A-Za-z0-9.-]*(?:OnlineExamHelp|ExamHelp|"
    r"DocsTeach|PastPapers|ExamTube)[A-Za-z0-9.-]*(?:\.[a-z]{2,})?"
    r"\s*\.?\s*\d*\s*(?=\n|$)", re.I)


def _strip_paper_tail(t):
    """从版权特征短语处截断到文末；找不到就不动（避免误伤正常正文）。"""
    cut = len(t)
    for cue in _PAPER_TAIL_CUES:
        i = t.lower().find(cue.lower())
        if i >= 0:
            cut = min(cut, i)
    # 页码行「Page N of M」出现在尾部时也一并裁掉
    m = None
    for m2 in re.finditer(r"(?:^|\n)Page\s+\d+\s+of\s+\d+\s*(?=\n|$)", t, re.I):
        m = m2
    if m:
        cut = min(cut, m.start())
    return t[:cut] if cut < len(t) else t
# 开头版权是「整行」形态（© UCLES 2022 / © Cambridge ... 2025 / Page 6 of 20），
# 逐行剥离即可 —— 不能用宽松正则跨行匹配，否则会把正文一起吃掉。
_PAPER_HEAD_LINE = re.compile(
    r"^(?:\s*©.*|\s*\(c\).*|\s*Cambridge University.*|\s*UCLES\s+\d{4}.*"
    r"|\s*Page\s+\d+\s+of\s+\d+\s*|\s*Photocopiable.*"
    r"|\s*Permission\s+to\s+reproduce.*|\s*Additional\s+Page.*"
    r"|\s*Do\s+not\s+write\s+in\s+this\s+margin.*)$", re.I)


def clean_paper_text(t):
    """出卷用：去版权/页眉页脚残留、去第三方站点水印、去 Latin-1 乱码、压过多空行。"""
    if not t:
        return ""
    lines = t.split("\n")
    # 只剥开头连续的版权/页眉行；遇到正文立即停止，不做全局替换
    while lines and (not lines[0].strip() or _PAPER_HEAD_LINE.match(lines[0])):
        lines.pop(0)
    t = "\n".join(lines)
    t = _strip_paper_tail(t)
    # 先按上面的正则整体清一遍；再逐个域名做兜底删除，处理
    # "com com 3" / "com 7 8" 这类域名与孤立页码交错、整体正则吃不全的形态
    t = _PAPER_WATERMARK.sub("", t)
    for _ in range(6):                      # 迭代到收敛，最多 6 轮防死循环
        t2 = re.sub(r"(?:www\.)?(?:OnlineExamHelp|ExamHelp|DocsTeach|PastPapers|ExamTube)"
                    r"[A-Za-z0-9.-]*\.(?:com|net|org|co\.uk|cn)(?:\s*\d+)*\s*",
                    "", t, flags=re.I)
        if t2 == t:
            break
        t = t2
    # OCR 常把版权段读成 Latin-1 乱码（如 "ĬÍĊ®Ġ´−ÈõÏĪ°ĊÝúµĂ×"），
    # 这类字符成串出现即为误读，直接丢弃，避免不可读文字混进卷子。
    t = re.sub(r"[Ā-ſ]{6,}", "", t)
    t = t.replace("�", "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def ability(con, sid):
    """按 engine.py 的规则重算能力分（服务端是权威，客户端只是缓存）。"""
    rows = con.execute("""SELECT a.qid, a.score, a.secs, q.topic_id, q.difficulty_p
                          FROM attempt a JOIN question q ON q.qid=a.qid
                          WHERE a.sid=? AND q.topic_id IS NOT NULL ORDER BY a.ts""", (sid,)).fetchall()
    ch = {t: p for t, p in con.execute("SELECT topic_id,parent_id FROM topic WHERE level='L2'")}
    elo, n = {}, {}
    for qid, score, secs, t, dp in rows:
        D = 800 + 800 * (1 - (dp if dp is not None else 0.5))
        s = score if score is not None else 0.0
        if s == 1 and (secs or 0) > SECS_SLOW: s = CREDIT_SLOW
        a = elo.get(t, INIT); k = max(K_LO, K_HI - n.get(t, 0) * 2)
        e = 1 / (1 + 10 ** ((D - a) / 400))
        elo[t] = a + k * (s - e); n[t] = n.get(t, 0) + 1
    # 必须把 L1 也放进查表：只放 L2 会让 chapter 恒为空
    names = {t: nm for t, nm in con.execute("SELECT topic_id,name_cn FROM topic")}
    out = []
    for t, a in elo.items():
        c = ch.get(t, ""); cn = names.get(c, "")
        # 作答不足时向章均值收缩
        if n[t] < MIN_T:
            sib = [elo[x] for x in elo if ch.get(x) == c and n.get(x, 0) >= MIN_T]
            if sib: a = 0.5 * a + 0.5 * sum(sib) / len(sib)
        out.append({"topic": t, "name": names.get(t, t), "chapter": cn,
                    "elo": round(a), "n": n[t], "reliable": n[t] >= SHOW_AT})
    out.sort(key=lambda x: x["elo"])
    return out, len(rows)

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
    def version_string(self):
        return "mathbank"          # 不暴露 Python/http.server 版本
    def _q(self):
        """http.server 用 iso-8859-1 解码请求行，中文查询参数会变乱码。
        正解：先 encode('latin-1') 还原原始字节，再解百分号、按 UTF-8 解码。
        这样「浏览器发的 %E6%B5%8B..」和「URL 里直接写中文」两种写法都对。"""
        raw = urllib.parse.urlparse(self.path).query
        b = urllib.parse.unquote_to_bytes(raw.encode("latin-1", "ignore"))
        return urllib.parse.parse_qs(b.decode("utf-8", "replace"))
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def end_headers(self):
        # 所有响应（静态 + API + 错误页）统一补安全头
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    # ----- 安全门 -----
    def _host_ok(self):
        if CLOUD:
            return True              # 云模式：Host 由平台反代控制
        h = (self.headers.get("Host") or "")
        host = h.rsplit(":", 1)[0].strip("[]").lower()
        return host in LOCAL_HOSTS
    def _static_denied(self):
        try:
            p = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        except Exception:
            return True
        low = p.lower()
        if ".." in p or "\x00" in p:
            return True
        return any(low.endswith(e) for e in DENIED_EXT)
    def _same_origin_write(self):
        """POST 写入：带 Origin/Referer 时必须同源（防跨站 text/plain JSON 伪造）。
        云模式：Origin/Referer 的 host 必须等于本次请求 Host（同源即放行，
        跨站伪造依然拦截）；本机模式：必须来自本机。"""
        req_host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        for hname in ("Origin", "Referer"):
            v = self.headers.get(hname)
            if not v:
                continue
            try:
                host = urllib.parse.urlparse(v).hostname or ""
            except Exception:
                return False
            if CLOUD:
                if host.lower() != req_host:
                    return False
            elif host not in LOCAL_HOSTS:
                return False
        return True

    def _client_ip(self):
        if CLOUD:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if xff:
                return xff[:45]
        return self.client_address[0] if self.client_address else "?"

    def do_GET(self):
        if not self._host_ok():
            return self._json({"err": "forbidden host"}, 403)
        if self._static_denied():
            return self._json({"err": "forbidden"}, 403)
        u = urllib.parse.urlparse(self.path); q = self._q()
        # ---- 会话/鉴权 ----
        if u.path == "/api/me":
            s = session_get(self)
            if not s:
                return self._json({"role": None})
            return self._json({"role": s["role"], "name": s["name"]})
        s = session_get(self)
        if u.path in ("/api/students", "/api/sync"):
            if not s or s["role"] != "teacher":
                return self._json({"err": "需要教师登录"}, 401)
        if u.path == "/api/quiz":
            if not s or s["role"] != "teacher":
                return self._json({"err": "需要教师登录"}, 401)
        if u.path == "/api/export":
            if not s:
                return self._json({"err": "需要登录"}, 401)
            # 只读身份判定用独立的 req_name / export_all 两个变量：
            # 早前这里复用了后面 export 分支还要再读一次的 name，
            # 结果学生「不带 name」的请求在下游被重置成""，落进「教师全员导出」分支，
            # 导致学生 token 能导出全班数据。两者必须分开，不可复用。
            req_name = ((q.get("name") or [""])[0] or "").strip()[:40]
            if s["role"] == "student":
                # 学生永远只能导出自己：即便显式传了 name=别人 也忽略，
                # 直接以 token 里的身份为准（原实现是返回 403，功能等价但更易被绕）
                req_name = s["name"]
            export_all = (s["role"] == "teacher" and not req_name)
        if u.path == "/api/sync":
            # 镜像守护增量拉取：since 为空 = 全量
            since = ((q.get("since") or [""])[0] or "").strip()[:40]
            con = db()
            if since:
                rows = con.execute("""SELECT a.aid, s.name, a.qid, a.ts, a.score, a.secs,
                                             a.err_type, a.resp_raw, a.self_report
                                      FROM attempt a JOIN student s ON s.sid=a.sid
                                      WHERE a.ts > ? ORDER BY a.ts""", (since,)).fetchall()
            else:
                rows = con.execute("""SELECT a.aid, s.name, a.qid, a.ts, a.score, a.secs,
                                             a.err_type, a.resp_raw, a.self_report
                                      FROM attempt a JOIN student s ON s.sid=a.sid
                                      ORDER BY a.ts""").fetchall()
            studs = [r[0] for r in con.execute("SELECT name FROM student ORDER BY name")]
            con.close()
            return self._json({"since": since, "students": studs, "attempts": [
                {"aid": r[0], "name": r[1], "qid": r[2], "ts": r[3], "score": r[4],
                 "secs": r[5], "err": r[6], "why": r[7], "self": r[8]} for r in rows]})
        if u.path == "/api/students":
            con = db()
            # last_ts / weak_top：教师要回答的是「该关注谁、该补什么」，
            # 只给累计题数与正确率无法排序也无法定位，必须带上最近活跃与最弱知识点。
            rows = con.execute("""SELECT s.name, s.created_at, COUNT(a.aid), AVG(a.score), MAX(a.ts)
                                  FROM student s LEFT JOIN attempt a ON a.sid=s.sid
                                  GROUP BY s.sid ORDER BY MAX(a.ts) DESC, s.name""").fetchall()
            out = []
            for nm, created, cnt, acc, last in rows:
                sid = con.execute("SELECT sid FROM student WHERE name=?", (nm,)).fetchone()[0]
                ab, _ = ability(con, sid)
                weak = sorted([b for b in ab if b["n"] >= 1],
                              key=lambda b: b["elo"])[:3]
                out.append({"name": nm, "n": cnt, "acc": round((acc or 0) * 100),
                            "created": created, "last": last,
                            "weak": [{"name": b["name"], "elo": round(b["elo"]),
                                      "n": b["n"]} for b in weak]})
            con.close()
            return self._json(out)
        if u.path == "/api/export":
            name = req_name                     # 已在鉴权段收敛：学生=自己，教师=指定或空
            if export_all:
                # 教师不带 name = 全员导出（镜像/备份用）；light=1 只回能力分（热力图用）
                light = ((q.get("light") or [""])[0] or "") == "1"
                con = db()
                out = {}
                for (nm,) in con.execute("SELECT name FROM student ORDER BY name"):
                    sid = con.execute("SELECT sid FROM student WHERE name=?", (nm,)).fetchone()[0]
                    ab, tot = ability(con, sid)
                    if light:
                        out[nm] = {"attempts": tot, "ability": ab}
                        continue
                    rows = con.execute("""SELECT qid,ts,score,secs,err_type,
                          (SELECT topic_id FROM question WHERE question.qid=attempt.qid)
                          FROM attempt WHERE sid=? ORDER BY ts""", (sid,)).fetchall()
                    out[nm] = {"attempts": tot, "ability": ab, "log": [
                        {"qid": r[0], "ts": r[1], "score": r[2], "secs": r[3],
                         "err": r[4], "topic": r[5]} for r in rows]}
                con.close()
                return self._json({"all": out})
            con = db()
            sid = get_sid_or_none(con, name)    # 只读查找：导出不建号
            if not sid:
                con.close()
                return self._json({"err": "学生不存在"}, 404)
            rows = con.execute("""SELECT aid, qid, ts, score, secs, err_type, resp_raw,
                                  (SELECT topic_id FROM question WHERE question.qid=attempt.qid)
                                  FROM attempt WHERE sid=? ORDER BY ts""", (sid,)).fetchall()
            ab, tot = ability(con, sid); con.close()
            return self._json({"name": name, "attempts": tot, "ability": ab,
                               "log": [{"aid": r[0], "qid": r[1], "ts": r[2], "score": r[3],
                                        "secs": r[4], "err": r[5], "why": r[6],
                                        "topic": r[7]} for r in rows]})
        if u.path == "/api/quiz":
            name = ((q.get("name") or [""])[0] or "").strip()[:40]
            unit = ((q.get("unit") or [""])[0] or "").strip()[:32]
            if not name:
                return self._json({"err": "缺少 name"}, 400)
            try:
                n = int((q.get("n") or ["10"])[0])
            except Exception:
                n = 10
            n = max(1, min(n, 50))          # 钳制：防超大 LIMIT
            con = db()
            sid = get_sid_or_none(con, name)   # 只读：拼错姓名返回 404，不建号
            if not sid:
                con.close()
                return self._json({"err": "学生不存在，请从花名册选择"}, 404)
            ab, _ = ability(con, sid)
            tops = [b["topic"] for b in ab if not b["reliable"]][:5] or [b["topic"] for b in ab[:5]]
            ph = ",".join("?" * len(tops)) or "''"
            rows = con.execute(f"""SELECT q.qid,q.stem_md,q.marks,q.topic_id,q.figs,q.answer_key,q.ms_md
                FROM question q
                WHERE q.topic_id IN ({ph}) {'AND q.unit=?' if unit else ''}
                ORDER BY RANDOM() LIMIT ?""",
                (*tops, *([unit] if unit else []), n)).fetchall()
            names = {t: nm for t, nm in con.execute("SELECT topic_id,name_cn FROM topic")}
            # 统计实际覆盖到的知识点，用于在卷头回显，避免静默降级成单单元卷
            covered = {}
            for r in rows:
                covered[names.get(r[3], r[3])] = covered.get(names.get(r[3], r[3]), 0) + 1
            con.close()
            import html
            KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.9/dist"

            def _imgs(figs):
                """figs 是 JSON 数组；只取 stem/full 图，判分细则图不要"""
                try:
                    arr = json.loads(figs) if figs else []
                except Exception:
                    return []
                out = []
                for a in arr:
                    f = a.get("file", "")
                    if f and "ms" not in f.lower() and "answer" not in f.lower():
                        out.append(f)
                return out

            blocks = []
            for i, r in enumerate(rows):
                figs = _imgs(r[4])
                figh = "".join(
                    f'<div class=fig><img src="{html.escape(f)}" alt="原卷题图" loading="lazy"></div>'
                    for f in figs)
                ans = (r[5] or "").strip()
                ms = clean_paper_text(r[6] or "")
                # 全库仅 1227/12064 题有 answer_key（多为 SMC/BMO 客观题）；
                # 解答题给不出简答，只能附判分细则原文 —— 对教师同样有用，
                # 总比光秃秃一道题好（早前版本两样都不给，卷子直接不可用）。
                tail = (f'<div class=ans>参考答案：{html.escape(ans)}</div>' if ans
                        else (f'<details class=msd><summary>判分细则（无简答）</summary>'
                              f'<div class=msbody>{html.escape(ms)}</div></details>' if ms else ""))
                blocks.append(f'<div class=q><div class=m>第 {i+1} 题 · '
                              f'{html.escape(names.get(r[3],""))} · {r[2]} 分</div>'
                              f'<div class=s>{clean_paper_text(r[1] or "")}</div>'
                              f'{figh}{tail}</div>')
            body = "".join(blocks)
            # 覆盖知识点回显：让教师看到这份卷子实际练了什么，而不是以为覆盖了 5 个弱项
            cov_txt = "、".join(f"{k}（{v}题）" for k, v in
                                sorted(covered.items(), key=lambda x: -x[1]))
            filter_note = (f'<p class=warn>已按单元「{html.escape(unit)}」筛选，'
                           f'薄弱知识点命中 {len(covered)} 个。</p>' if unit else "")
            doc = ('<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8><title>专项练习</title>'
                   f'<link rel=stylesheet href="{KATEX}/katex.min.css">'
                   f'<script defer src="{KATEX}/katex.min.js"></script>'
                   f'<script defer src="{KATEX}/contrib/auto-render.min.js"></script>'
                   '<style>body{font:15px/1.8 system-ui,"PingFang SC";max-width:780px;margin:24px auto;'
                   'padding:0 16px}.q{margin:22px 0;padding-bottom:18px;border-bottom:1px dashed #bbb}'
                   '.m{color:#666;font-size:13px}.s{white-space:pre-wrap}'
                   '.warn{color:#a05a00;background:#fff6e6;padding:8px 12px;border-radius:8px}'
                   '.cov{color:#555;font-size:13px}.fig img{max-width:100%;border:1px solid #ddd;'
                   'border-radius:6px;margin-top:8px}'
                   '.ans{margin-top:10px;padding:8px 12px;background:#f2f7f2;border-left:3px solid #4a8;'
                   'border-radius:0 6px 6px 0;color:#245}'
                   '.msd{margin-top:10px;border:1px solid #ddd;border-radius:8px;overflow:hidden}'
                   '.msd>summary{cursor:pointer;padding:7px 12px;font-size:13px;color:#555;'
                   'background:#fafafa;list-style:none}.msd>summary::-webkit-details-marker{display:none}'
                   '.msd>summary::before{content:"▸ ";color:#999}'
                   '.msd[open]>summary::before{content:"▾ "}'
                   '.msbody{padding:10px 12px;white-space:pre-wrap;font-size:13.5px;color:#333;'
                   'border-top:1px solid #eee}</style></head><body>'
                   f'<h2>{html.escape(name)} · 薄弱点专项练习（{len(rows)} 题）</h2>'
                   f'<p class=m>按引擎判定的薄弱知识点抽取 · {time.strftime("%Y-%m-%d %H:%M")}</p>'
                   f'<p class=cov>实际覆盖 {len(covered)} 个知识点：{html.escape(cov_txt)}</p>'
                   f'{filter_note}{body}'
                   '<script>window.addEventListener("load",function(){'
                   'if(window.renderMathInElement)renderMathInElement(document.body,{delimiters:'
                   '[{left:"$$",right:"$$",display:true},{left:"\\\\[",right:"\\\\]",display:true},'
                   '{left:"\\\\(",right:"\\\\)",display:false},{left:"$",right:"$",display:false}],'
                   'throwOnError:false,ignoredTags:["script","style"]});});</script>'
                   '</body></html>')
            b = doc.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            return
        return super().do_GET()

    def do_HEAD(self):
        if not self._host_ok():
            return self._json({"err": "forbidden host"}, 403)
        if self._static_denied():
            return self._json({"err": "forbidden"}, 403)
        return super().do_HEAD()

    def do_POST(self):
        if not self._host_ok():
            return self._json({"err": "forbidden host"}, 403)
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/api/attempt", "/api/login", "/api/logout"):
            return self._json({"err": "not found"}, 404)
        if not self._same_origin_write():
            return self._json({"err": "cross-origin denied"}, 403)
        ip = self._client_ip()
        if not rate_ok(ip):
            return self._json({"err": "too many requests"}, 429)
        try:
            ln = int(self.headers.get("Content-Length") or 0)
        except Exception:
            ln = -1
        if ln < 0 or ln > MAX_BODY:
            return self._json({"err": "bad content-length"}, 413)
        try:
            d = json.loads(self.rfile.read(ln) or b"{}")
        except Exception as e:
            return self._json({"err": f"bad json: {e}"}, 400)
        if not isinstance(d, dict):
            return self._json({"err": "bad json"}, 400)

        # ---- 登录 / 注销 ----
        if path == "/api/logout":
            session_drop(self)
            return self._json({"ok": True})
        if path == "/api/login":
            role = str(d.get("role") or "")
            pw = str(d.get("pass") or "")[:128]
            if role == "teacher":
                if not secrets.compare_digest(pw, TEACHER_KEY):
                    return self._json({"err": "口令不对"}, 401)
                return self._json({"token": session_new("teacher", "教师"), "role": "teacher",
                                   "name": "教师"})
            if role == "student":
                name = str(d.get("name") or "").strip()[:40]
                if not name:
                    return self._json({"err": "缺少姓名"}, 400)
                if not secrets.compare_digest(pw, STUDENT_CODE):
                    return self._json({"err": "班级码不对"}, 401)
                con = db(); sid = get_sid(con, name); con.close()
                return self._json({"token": session_new("student", name, sid),
                                   "role": "student", "name": name})
            return self._json({"err": "role 必须是 teacher/student"}, 400)

        # ---- 作答：必须持学生 token，身份以 token 为准 ----
        sess = session_get(self)
        if not sess:
            return self._json({"err": "未登录"}, 401)
        if sess["role"] != "student":
            return self._json({"err": "教师账号不能作答"}, 403)
        name = sess["name"]
        # ---- 输入校验（全部钳制/白名单化；name 已由 token 决定，不信 body）----
        qid = str(d.get("qid") or "").strip()
        if not name or not QID_RE.match(qid):
            return self._json({"err": "qid 非法"}, 400)
        topic = str(d.get("topic") or "").strip()
        if topic and not TOPIC_RE.match(topic):
            topic = ""
        try:
            score = float(d.get("score"))
        except Exception:
            score = -1
        if score not in (0.0, 0.5, 1.0):
            return self._json({"err": "score 必须是 0/0.5/1"}, 400)
        try:
            secs = int(d.get("secs") or 0)
        except Exception:
            secs = 0
        secs = max(0, min(secs, 7200))
        try:
            marks = float(d.get("marks") or 0)
        except Exception:
            marks = 0.0
        marks = max(0.0, min(marks, 500.0))
        why = str(d.get("why") or "")[:500]
        err = d.get("err")
        err = err if (isinstance(err, str) and err in ERR_SET) else None
        # 客户端生成的 aid（重发幂等：同一条作答重试不会重复入库）
        aid = str(d.get("aid") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16,32}", aid):
            aid = uuid.uuid4().hex[:16]
        con = db(); sid = get_sid(con, name)
        con.execute("""INSERT OR IGNORE INTO attempt
            (aid,sid,qid,ts,resp_raw,self_report,score,score_max,rubric_hits,grader,err_type,secs)
            VALUES (?,?,?,datetime('now'),?,?,?,?,NULL,'self',?,?)""",
            (aid, sid, qid, None, why, score,
             marks, err, secs))
        con.commit()
        ab, tot = ability(con, sid)
        cur = next((b for b in ab if b["topic"] == topic), None)
        con.close()
        return self._json({"ok": True, "attempts": tot, "topic": cur})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    a = ap.parse_args()
    if not os.path.exists(DB):
        sys.exit(f"缺 {DB}，先跑 migrate.py / remap.py")
    port = int(os.environ.get("PORT") or a.port)
    host = "0.0.0.0" if CLOUD else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), H)
    if CLOUD:
        print(f"练习站(云模式): 0.0.0.0:{port}   数据写入 {DB}")
    else:
        print(f"练习站: http://127.0.0.1:{port}/   （仅本机可访问，数据写入 {DB}）")
        print(f"教师口令: {TEACHER_KEY}   学生班级码: {STUDENT_CODE}"
              f"   （可用环境变量 TEACHER_KEY / STUDENT_CODE 覆盖，"
              f"或改 {BASE}/.teacher_key / .student_code）")
    print("Ctrl+C 停止")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\n已停止")

if __name__ == "__main__":
    main()
