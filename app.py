"""
app.py — Streamlit Frontend (all-in-one)
==========================================
Chạy:  streamlit run app.py
Biến:  API_URL=http://localhost:8000 (mặc định)
"""

import os
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

API = os.getenv("API_URL", "http://localhost:8000")
ALGO_COLORS = {"astar": "#2563EB", "dijkstra": "#DC2626"}
ALGO_NAMES  = {"astar": "A* (A-Star)", "dijkstra": "Dijkstra"}


# ══════════════════════════════════════════════════════════════════════════════
# API CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def _h() -> dict:
    """Trả về Authorization header nếu đã đăng nhập."""
    t = st.session_state.get("token", "")
    return {"Authorization": f"Bearer {t}"} if t else {}

def _call(method: str, path: str, body=None, timeout=30):
    """Gọi API, trả về (data | None, error_msg | None)."""
    try:
        r = getattr(requests, method)(f"{API}{path}", json=body,
                                      headers=_h(), timeout=timeout)
        return (r.json(), None) if r.ok else (None, r.json().get("detail", r.text))
    except requests.exceptions.ConnectionError:
        return None, f"Không kết nối được server ({API}). Backend đang chạy chưa?"
    except Exception as e:
        return None, str(e)

# Shortcuts
def api_login(u, p):          return _call("post",   "/api/auth/login",        {"username": u, "password": p})
def api_presets():             return _call("get",    "/api/locations/presets")
def api_route(sl,sn,el,en,a): return _call("post",   "/api/route",             {"start_lat":sl,"start_lon":sn,"end_lat":el,"end_lon":en,"algorithm":a}, timeout=90)
def api_graph_info():          return _call("get",    "/api/graph/info")
def api_graph_build():         return _call("post",   "/api/graph/build",       timeout=600)
def api_graph_reload():        return _call("post",   "/api/graph/reload")
def api_users():               return _call("get",    "/api/admin/users")
def api_create_user(u,p,r):    return _call("post",   "/api/admin/users",       {"username":u,"password":p,"role":r})
def api_update_user(u,**kw):   return _call("put",    f"/api/admin/users/{u}",  {k:v for k,v in kw.items() if v is not None})
def api_delete_user(u):        return _call("delete", f"/api/admin/users/{u}")
def api_health():              return _call("get",    "/health",                timeout=5)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def init():
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("token",     "")
    st.session_state.setdefault("username",  "")
    st.session_state.setdefault("role",      "")
    st.session_state.setdefault("presets",   None)

def do_login(username, password):
    data, err = api_login(username, password)
    if err:
        st.error(f"❌ {err}"); return
    st.session_state.update(logged_in=True, token=data["access_token"],
                             username=data["username"], role=data["role"])
    st.rerun()

def do_logout():
    st.session_state.update(logged_in=False, token="", username="",
                             role="", presets=None)
    st.rerun()

def presets() -> dict[str, tuple]:
    if not st.session_state["presets"]:
        data, _ = api_presets()
        if data:
            st.session_state["presets"] = {
                i["name"]: (i["lat"], i["lon"]) for i in data["locations"]
            }
    return st.session_state["presets"] or {}


# ══════════════════════════════════════════════════════════════════════════════
# SHARED WIDGET: Routing Form + Map
# ══════════════════════════════════════════════════════════════════════════════

def routing_widget(key: str):
    locs  = presets()
    names = list(locs.keys())

    mode = st.radio("Chế độ nhập", ["📍 Địa điểm có sẵn", "🔢 Tọa độ thủ công"],
                    key=f"{key}_mode", horizontal=True)

    if mode == "📍 Địa điểm có sẵn" and names:
        sn = st.selectbox("🟢 Xuất phát", names, index=0, key=f"{key}_sn")
        en = st.selectbox("🔴 Điểm đến",  names, index=1, key=f"{key}_en")
        slat, slon = locs[sn];  elat, elon = locs[en]
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("🟢 Xuất phát")
            slat = st.number_input("Lat", value=42.3744, format="%.6f", key=f"{key}_slat")
            slon = st.number_input("Lon", value=-71.1169, format="%.6f", key=f"{key}_slon")
        with c2:
            st.caption("🔴 Điểm đến")
            elat = st.number_input("Lat", value=42.3601, format="%.6f", key=f"{key}_elat")
            elon = st.number_input("Lon", value=-71.0942, format="%.6f", key=f"{key}_elon")

    st.divider()
    algo_label = st.radio("⚙️ Thuật toán", ["A* (A-Star)", "Dijkstra"],
                           key=f"{key}_algo", horizontal=True)
    algo    = "astar" if "A*" in algo_label else "dijkstra"
    compare = st.checkbox("📊 So sánh cả hai thuật toán", key=f"{key}_cmp")
    run_btn = st.button("🚀 Tìm đường", type="primary",
                         use_container_width=True, key=f"{key}_run")

    # Map base
    m = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron")
    folium.Marker([slat, slon], tooltip="Xuất phát",
                  icon=folium.Icon(color="green", icon="play",  prefix="fa")).add_to(m)
    folium.Marker([elat, elon], tooltip="Điểm đến",
                  icon=folium.Icon(color="red",   icon="flag",  prefix="fa")).add_to(m)

    if run_btn:
        algos = ["astar","dijkstra"] if compare else [algo]
        results, first_coords = [], None

        with st.spinner("Đang tính toán…"):
            for a in algos:
                data, err = api_route(slat, slon, elat, elon, a)
                if err:
                    st.error(f"❌ {ALGO_NAMES[a]}: {err}"); continue
                if not data["found"]:
                    st.warning(f"⚠️ {ALGO_NAMES[a]}: {data.get('error','')}"); continue

                coords = [tuple(c) for c in data["path_coordinates"]]
                folium.PolyLine(coords, weight=5, color=ALGO_COLORS[a], opacity=0.85,
                                tooltip=f"{ALGO_NAMES[a]}: {data['total_distance_m']/1000:.2f} km"
                                ).add_to(m)
                results.append((a, data))
                first_coords = first_coords or coords

        if first_coords:
            m.fit_bounds([[min(c[0] for c in first_coords), min(c[1] for c in first_coords)],
                          [max(c[0] for c in first_coords), max(c[1] for c in first_coords)]])
        if results:
            st.success("✅ Tìm đường thành công!")
            for col, (a, d) in zip(st.columns(len(results)), results):
                with col:
                    st.markdown(f"<span style='color:{ALGO_COLORS[a]};font-weight:700'>"
                                f"{ALGO_NAMES[a]}</span>", unsafe_allow_html=True)
                    st.metric("📏 Khoảng cách",     f"{d['total_distance_m']/1000:.3f} km")
                    st.metric("⏱️ Thời gian xử lý", f"{d['exec_time_ms']:.1f} ms")
                    st.metric("📍 Số node",          f"{d['node_count']:,}")

    st_folium(m, use_container_width=True, height=560)


# ══════════════════════════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════════════════════════

def page_login():
    st.markdown("""
    <div style='text-align:center;padding:50px 0 10px'>
      <h1>🗺️ Boston Route Finder</h1>
      <p style='opacity:.6'>Location-Based Service — Đăng nhập để tiếp tục</p>
    </div>""", unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("login"):
            u = st.text_input("Tên đăng nhập", placeholder="admin / user")
            p = st.text_input("Mật khẩu", type="password")
            if st.form_submit_button("🔑 Đăng nhập", use_container_width=True):
                do_login(u, p)
        st.caption("Demo: **admin**/admin123  ·  **user**/user123")

    data, err = api_health()
    if err:
        st.warning(f"⚠️ Backend chưa sẵn sàng: {err}")
    else:
        g = "✓ loaded" if data.get("graph_loaded") else "⏳ chưa load"
        st.success(f"✅ Backend online — Graph: {g}")


def page_user():
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/"
                 "Flag_of_Massachusetts.svg/320px-Flag_of_Massachusetts.svg.png",
                 use_container_width=True)
        st.markdown(f"👤 **{st.session_state['username']}**")
        st.divider()
        routing_widget("u")
        st.divider()
        if st.button("🚪 Đăng xuất", use_container_width=True): do_logout()


def page_admin():
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/"
                 "Flag_of_Massachusetts.svg/320px-Flag_of_Massachusetts.svg.png",
                 use_container_width=True)
        st.markdown(f"🛡️ **{st.session_state['username']}** *(admin)*")
        st.divider()
        menu = st.radio("📋 Menu", ["🗺️ Bản đồ", "👥 Tài khoản", "⚙️ Dữ liệu"])
        st.divider()
        if st.button("🚪 Đăng xuất", use_container_width=True): do_logout()

    if   menu == "🗺️ Bản đồ":   _map_tab()
    elif menu == "👥 Tài khoản": _users_tab()
    else:                        _data_tab()


# ── Admin sub-pages ────────────────────────────────────────────────────────────

def _map_tab():
    st.title("🗺️ Bản đồ Boston — Tìm đường")
    routing_widget("a")


def _users_tab():
    st.title("👥 Quản lý tài khoản")
    users, err = api_users()
    if err: st.error(err); return

    own = st.session_state["username"]
    for u in users:
        with st.expander(f"{'🟢' if u['active'] else '🔴'} **{u['username']}** — {u['role']}"):
            disabled = (u["username"] == own)
            c1, c2 = st.columns(2)
            with c1:
                nr = st.selectbox("Vai trò", ["user","admin"],
                                  index=0 if u["role"]=="user" else 1,
                                  key=f"r_{u['username']}", disabled=disabled)
                na = st.checkbox("Hoạt động", u["active"],
                                  key=f"a_{u['username']}", disabled=disabled)
            with c2:
                np_ = st.text_input("Mật khẩu mới", type="password", key=f"p_{u['username']}")

            cs, cd = st.columns(2)
            with cs:
                if st.button("💾 Lưu", key=f"s_{u['username']}"):
                    kw = {"role": nr, "active": na}
                    if np_: kw["password"] = np_
                    _, e = api_update_user(u["username"], **kw)
                    st.error(e) if e else (st.success("✅ Đã cập nhật!") or st.rerun())
            with cd:
                if not disabled and st.button("🗑️ Xóa", key=f"d_{u['username']}"):
                    _, e = api_delete_user(u["username"])
                    st.error(e) if e else (st.success("✅ Đã xóa!") or st.rerun())

    st.divider()
    st.subheader("➕ Tạo tài khoản mới")
    with st.form("nu"):
        nu = st.text_input("Tên đăng nhập")
        np_ = st.text_input("Mật khẩu", type="password")
        nr = st.selectbox("Vai trò", ["user","admin"])
        if st.form_submit_button("✅ Tạo"):
            _, e = api_create_user(nu, np_, nr)
            st.error(f"❌ {e}") if e else (st.success(f"✅ Đã tạo **{nu}**!") or st.rerun())


def _data_tab():
    st.title("⚙️ Quản lý dữ liệu không gian")
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.subheader("📊 Trạng thái")
        info, err = api_graph_info()
        if err: st.error(err)
        elif info["loaded"]:
            st.success("✅ Đồ thị hoạt động trong RAM")
            st.info(f"- **Nodes:** {info['node_count']:,}\n"
                    f"- **Edges:** {info['edge_count']:,}\n"
                    f"- **PBF:** `{info['pbf_path']}`\n"
                    f"- **PKL:** `{info['graph_path']}`")
        else:
            st.warning("⚠️ Đồ thị chưa được load")

    with c2:
        st.subheader("🔧 Thao tác")
        if st.button("🏗️ Build từ PBF", type="primary",
                     help="Parse .pbf, lưu .pkl, cập nhật RAM (~3-8 phút)"):
            with st.spinner("Đang build…"):
                res, err = api_graph_build()
            if err: st.error(f"❌ {err}")
            else: st.success(f"✅ {res['node_count']:,} nodes · {res['edge_count']:,} edges")

        if st.button("🔃 Reload từ .pkl"):
            res, err = api_graph_reload()
            if err: st.error(f"❌ {err}")
            else: st.success(f"✅ {res['node_count']:,} nodes · {res['edge_count']:,} edges")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Boston Route Finder", page_icon="🗺️",
                   layout="wide", initial_sidebar_state="expanded")
init()

if   not st.session_state["logged_in"]:       page_login()
elif st.session_state["role"] == "admin":      page_admin()
else:                                          page_user()
