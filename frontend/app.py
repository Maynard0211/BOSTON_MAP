"""
frontend/app.py — Streamlit Interactive Frontend
================================================
Run: streamlit run frontend/app.py
Config: API_URL=http://localhost:8000 (default)
"""

import os
import requests
import json
import streamlit as st
import folium
from streamlit_folium import st_folium

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG & PATHS
# ══════════════════════════════════════════════════════════════════════════════

FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(FRONTEND_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

LAST_ROUTE_FILE = os.getenv("LAST_ROUTE_PATH", os.path.join(DATA_DIR, "last_route.json"))
API = os.getenv("API_URL", "http://localhost:8000")

ALGO_COLORS = {"astar": "#2563EB", "dijkstra": "#60A5FA"}
ALGO_NAMES = {"astar": "A* (A-Star)", "dijkstra": "Dijkstra"}


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_last_route() -> dict:
    """Loads previously saved route parameters from JSON."""
    if os.path.exists(LAST_ROUTE_FILE):
        try:
            with open(LAST_ROUTE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_last_route(data: dict):
    """Saves selected route parameters to JSON."""
    try:
        with open(LAST_ROUTE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# API CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def _call(method: str, path: str, body=None, timeout=30):
    """Executes HTTP request to FastAPI backend, returning (data | None, error_msg | None)."""
    try:
        r = getattr(requests, method)(f"{API}{path}", json=body, timeout=timeout)
        return (r.json(), None) if r.ok else (None, r.json().get("detail", r.text))
    except requests.exceptions.ConnectionError:
        return None, f"Không thể kết nối tới máy chủ backend ({API}). Vui lòng đảm bảo backend đang chạy."
    except Exception as e:
        return None, str(e)


def api_presets():
    return _call("get", "/api/locations/presets")


def api_route(sl, sn, el, en, a):
    return _call(
        "post",
        "/api/route",
        {"start_lat": sl, "start_lon": sn, "end_lat": el, "end_lon": en, "algorithm": a},
        timeout=90
    )


def api_graph_info():
    return _call("get", "/api/graph/info")


def api_graph_build():
    return _call("post", "/api/graph/build", timeout=600)


def api_graph_reload():
    return _call("post", "/api/graph/reload")


def api_health():
    return _call("get", "/health", timeout=5)


def api_blocked_edges():
    return _call("get", "/api/graph/blocked")


def api_block_edge(u, v):
    return _call("post", "/api/graph/blocked", {"u": u, "v": v})


def api_unblock_edge(u, v):
    return _call("delete", f"/api/graph/blocked?u={u}&v={v}")


def api_clear_blocked():
    return _call("post", "/api/graph/blocked/clear")


def api_nearest_node(lat, lon):
    return _call("get", f"/api/graph/nearest?lat={lat}&lon={lon}")


def api_node_adjacent(node_id):
    return _call("get", f"/api/graph/node-adjacent/{node_id}")


def api_nearest_edge(lat, lon):
    return _call("get", f"/api/graph/nearest-edge?lat={lat}&lon={lon}")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

def init():
    st.session_state.setdefault("role", "user")
    st.session_state.setdefault("presets", None)
    st.session_state.setdefault("selected_node", None)
    st.session_state.setdefault("adjacent_edges", None)
    st.session_state.setdefault("last_route", load_last_route())


def presets():
    if not st.session_state.get("presets"):
        data, _ = api_presets()
        if data and "locations" in data:
            st.session_state["presets"] = {
                i["name"]: (i["lat"], i["lon"]) for i in data["locations"]
            }
    return st.session_state.get("presets") or {}


# ══════════════════════════════════════════════════════════════════════════════
# SHARED ROUTING WIDGET
# ══════════════════════════════════════════════════════════════════════════════

def routing_widget(key: str):
    locs = presets()
    names = list(locs.keys())
    last = st.session_state.get("last_route", {})

    st.session_state.setdefault(f"{key}_start_coords", None)
    st.session_state.setdefault(f"{key}_end_coords", None)
    st.session_state.setdefault(f"{key}_click_count", 0)
    st.session_state.setdefault(f"{key}_last_processed_click", None)
    st.session_state.setdefault(f"{key}_view_state", "input")
    st.session_state.setdefault(f"{key}_results", None)

    start_coords = st.session_state[f"{key}_start_coords"]
    slat, slon = start_coords if start_coords else (None, None)
    end_coords = st.session_state[f"{key}_end_coords"]
    elat, elon = end_coords if end_coords else (None, None)

    col_left, col_right = st.columns([7, 3])

    sn, en = "", ""
    algo = "astar"
    compare = False
    run_btn = False
    reset_btn = False

    with col_right:
        # 1. VIEW: ROUTING RESULTS
        if st.session_state[f"{key}_view_state"] == "result" and st.session_state[f"{key}_results"]:
            st.markdown("### 📍 Kết Quả Tìm Đường")

            if st.button("⬅ Tìm kiếm hành trình mới", use_container_width=True):
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
                st.rerun()

            st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)

            results = st.session_state[f"{key}_results"]
            for a, d in results:
                card_html = f"""
                <div style='background: #F8FAFC; border-left: 5px solid {ALGO_COLORS[a]}; padding: 12px; border-radius: 6px; margin-bottom: 10px; border: 1px solid #E2E8F0;'>
                    <div style='color:{ALGO_COLORS[a]}; font-size: 1.05rem; font-weight: 700; margin-bottom: 6px;'>
                        ⚡ {ALGO_NAMES[a]}
                    </div>
                    <div style='font-size: 0.9rem; color: #1E293B;'>
                        <div>📏 <b>Khoảng cách:</b> {d['total_distance_m']/1000:.3f} km ({d['total_distance_m']:.1f} m)</div>
                        <div>⏱️ <b>Thời gian xử lý:</b> {d['exec_time_ms']:.2f} ms</div>
                        <div>🔗 <b>Số nút giao (Nodes):</b> {d['node_count']:,}</div>
                    </div>
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)

        # 2. VIEW: INPUT FORM
        else:
            default_mode_idx = 0 if last.get("mode") == "Địa điểm có sẵn" else 1
            if default_mode_idx == 0 and not names:
                default_mode_idx = 1

            mode = st.radio(
                "Phương thức chọn điểm",
                ["Địa điểm có sẵn", "Tọa độ / Bản đồ"],
                index=default_mode_idx,
                key=f"{key}_mode",
                horizontal=True
            )

            if mode == "Tọa độ / Bản đồ":
                cnt = st.session_state[f"{key}_click_count"]
                if cnt == 0:
                    st.info("📍 **Bước 1:** Click chuột lên bản đồ để chọn **Điểm xuất phát**.")
                elif cnt == 1:
                    st.info("🎯 **Bước 2:** Click tiếp lên bản đồ để chọn **Điểm đến**.")
                elif cnt == 2:
                    st.success("🏁 Đã chọn đủ 2 điểm. Nhấp **Tìm đường** hoặc click lại bản đồ để chọn lại.")

            with st.form(f"{key}_routing_form"):
                if mode == "Địa điểm có sẵn" and names:
                    default_sn_idx = names.index(last["sn"]) if "sn" in last and last["sn"] in names else 0
                    default_en_idx = names.index(last["en"]) if "en" in last and last["en"] in names else (1 if len(names) > 1 else 0)

                    sn = st.selectbox("Điểm xuất phát", names, index=default_sn_idx, key=f"{key}_sn_form")
                    en = st.selectbox("Điểm đến", names, index=default_en_idx, key=f"{key}_en_form")
                else:
                    st.caption("Điểm xuất phát (Vĩ độ / Kinh độ)")
                    c_slat, c_slon = st.columns(2)
                    with c_slat:
                        slat_input = st.number_input("Vĩ độ đi", value=slat, format="%.6f", label_visibility="collapsed", placeholder="Vĩ độ")
                    with c_slon:
                        slon_input = st.number_input("Kinh độ đi", value=slon, format="%.6f", label_visibility="collapsed", placeholder="Kinh độ")

                    st.caption("Điểm đến (Vĩ độ / Kinh độ)")
                    c_elat, c_elon = st.columns(2)
                    with c_elat:
                        elat_input = st.number_input("Vĩ độ đến", value=elat, format="%.6f", label_visibility="collapsed", placeholder="Vĩ độ")
                    with c_elon:
                        elon_input = st.number_input("Kinh độ đến", value=elon, format="%.6f", label_visibility="collapsed", placeholder="Kinh độ")

                st.markdown("<hr style='margin: 8px 0;'>", unsafe_allow_html=True)

                default_algo_idx = 0 if last.get("algo") == "astar" else 1
                algo_label = st.radio(
                    "Thuật toán",
                    ["A* (A-Star)", "Dijkstra"],
                    index=default_algo_idx,
                    key=f"{key}_algo_form",
                    horizontal=True
                )
                algo = "astar" if "A*" in algo_label else "dijkstra"

                default_compare = last.get("compare", False)
                compare = st.checkbox("So sánh song song cả hai thuật toán", value=default_compare, key=f"{key}_cmp_form")

                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    run_btn = st.form_submit_button("🚀 Tìm đường", type="primary", use_container_width=True)
                with c_btn2:
                    reset_btn = st.form_submit_button("🔄 Đặt lại", use_container_width=True)

    if reset_btn and mode == "Tọa độ / Bản đồ":
        st.session_state[f"{key}_start_coords"] = None
        st.session_state[f"{key}_end_coords"] = None
        st.session_state[f"{key}_click_count"] = 0
        st.session_state[f"{key}_last_processed_click"] = None
        st.session_state[f"{key}_view_state"] = "input"
        st.session_state[f"{key}_results"] = None
        st.rerun()

    if run_btn:
        if mode == "Địa điểm có sẵn" and names:
            slat, slon = locs[sn]
            elat, elon = locs[en]
            st.session_state[f"{key}_start_coords"] = (slat, slon)
            st.session_state[f"{key}_end_coords"] = (elat, elon)
        else:
            slat, slon = slat_input, slon_input
            elat, elon = elat_input, elon_input

            if slat is None or slon is None or elat is None or elon is None:
                st.error("Vui lòng chọn hoặc nhập đầy đủ cả điểm đi và điểm đến!")
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
            else:
                st.session_state[f"{key}_start_coords"] = (slat, slon)
                st.session_state[f"{key}_end_coords"] = (elat, elon)

        if elat and elon and slat and slon:
            algos = ["astar", "dijkstra"] if compare else [algo]
            results_list = []

            with st.spinner("Đang tối ưu hóa đường đi..."):
                for a in algos:
                    data, err = api_route(slat, slon, elat, elon, a)
                    if err:
                        with col_right:
                            st.error(f"{ALGO_NAMES[a]}: {err}")
                        continue
                    if not data.get("found"):
                        with col_right:
                            st.warning(f"{ALGO_NAMES[a]}: {data.get('error', 'Không tìm thấy đường đi.')}")
                        continue
                    results_list.append((a, data))

            if results_list:
                st.session_state[f"{key}_results"] = results_list
                st.session_state[f"{key}_view_state"] = "result"

                save_last_route({
                    "mode": mode,
                    "sn": sn if mode == "Địa điểm có sẵn" else "",
                    "en": en if mode == "Địa điểm có sẵn" else "",
                    "slat": slat,
                    "slon": slon,
                    "elat": elat,
                    "elon": elon,
                    "algo": algo,
                    "compare": compare
                })
                st.session_state["last_route"] = load_last_route()
                st.rerun()

    # Base Folium Map
    m = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron", scrollWheelZoom=False)

    if slat and slon:
        folium.Marker(
            [slat, slon],
            tooltip="Điểm xuất phát",
            icon=folium.Icon(color="blue", icon="map-marker", prefix="fa")
        ).add_to(m)

    if elat and elon:
        folium.Marker(
            [elat, elon],
            tooltip="Điểm đến",
            icon=folium.Icon(color="red", icon="flag", prefix="fa")
        ).add_to(m)

    # Render Blocked Roads (Red Dashed Lines)
    blocked_data, _ = api_blocked_edges()
    if blocked_data:
        for edge in blocked_data:
            coords = [tuple(c) for c in edge["coords"]]
            folium.PolyLine(
                coords,
                weight=5,
                color="#EF4444",
                opacity=0.9,
                dash_array="5, 8",
                tooltip=f"Đoạn đường đang chặn: {edge['name']}"
            ).add_to(m)

    # Render Computed Route PolyLines
    first_coords = None
    results = st.session_state.get(f"{key}_results")
    if results:
        for a, d in results:
            coords = [tuple(c) for c in d["path_coordinates"]]
            folium.PolyLine(
                coords,
                weight=5,
                color=ALGO_COLORS[a],
                opacity=0.85,
                tooltip=f"{ALGO_NAMES[a]}: {d['total_distance_m']/1000:.2f} km ({d['exec_time_ms']:.1f} ms)"
            ).add_to(m)
            first_coords = first_coords or coords

        if first_coords:
            m.fit_bounds([
                [min(c[0] for c in first_coords), min(c[1] for c in first_coords)],
                [max(c[0] for c in first_coords), max(c[1] for c in first_coords)]
            ])

    # Left Column: Map Rendering & Click Capturing
    with col_left:
        map_data = st_folium(m, use_container_width=True, height=420, key=f"{key}_map_render", returned_objects=["last_clicked"])

        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            click_coord = (last_clicked["lat"], last_clicked["lng"])
            if st.session_state[f"{key}_last_processed_click"] != click_coord:
                st.session_state[f"{key}_last_processed_click"] = click_coord
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None

                cnt = st.session_state[f"{key}_click_count"]
                if cnt == 0:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    st.rerun()
                elif cnt == 1:
                    st.session_state[f"{key}_end_coords"] = click_coord
                    st.session_state[f"{key}_click_count"] = 2
                    st.rerun()
                elif cnt == 2:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# VIEWS: USER & ADMIN
# ══════════════════════════════════════════════════════════════════════════════

def page_user():
    st.markdown("""
    <div style='text-align:center; padding: 14px 12px; background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%); border-radius: 8px; margin-bottom: 14px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.08);'>
      <h1 style='margin:0; font-size: 1.8rem !important; font-weight: 800; color: white !important;'>🗺️ Boston Smart Route Finder</h1>
      <p style='opacity:0.95; margin: 4px 0 0 0; font-size: 0.95rem !important;'>Hệ thống tìm đường đi ngắn nhất thông minh và tránh sự cố giao thông đô thị</p>
    </div>""", unsafe_allow_html=True)
    routing_widget("user_routing")


def _map_tab():
    st.subheader("Tìm kiếm lộ trình")
    routing_widget("admin_routing")


def _blocked_roads_tab():
    st.subheader("🚧 Quản lý Chặn Tuyến Đường (Road Blocking Simulation)")
    st.caption("Mô phỏng sự cố tai nạn hoặc công trình thi công. Thuật toán tìm đường sẽ tự động đổi lộ trình để né tránh.")

    blocked_list, _ = api_blocked_edges()

    st.session_state.setdefault("admin_last_clicked", None)
    st.session_state.setdefault("selected_edge", None)

    m_admin = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron", scrollWheelZoom=False)

    if blocked_list:
        for edge in blocked_list:
            coords = [tuple(c) for c in edge["coords"]]
            folium.PolyLine(
                coords,
                weight=5,
                color="#DC2626",
                opacity=0.9,
                dash_array="5, 8",
                tooltip=f"Đang chặn: {edge['name']}"
            ).add_to(m_admin)

    if st.session_state["admin_last_clicked"]:
        clat, clon = st.session_state["admin_last_clicked"]
        folium.Marker(
            [clat, clon],
            tooltip="Vị trí đã chọn",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(m_admin)

    if st.session_state["selected_edge"]:
        edge = st.session_state["selected_edge"]
        folium.PolyLine(
            edge["coords"],
            weight=8,
            color="#F59E0B",
            opacity=0.9,
            tooltip=f"Tuyến đường đang chọn: {edge['highway']} ({edge['u']} -> {edge['v']})"
        ).add_to(m_admin)

    c1, c2 = st.columns([7, 3])

    with c1:
        st.info("👉 Click chuột trực tiếp lên bất kỳ con đường nào trên bản đồ để chọn đoạn đường cần chặn.")
        map_data = st_folium(m_admin, use_container_width=True, height=420, key="admin_blocking_map", returned_objects=["last_clicked"])

        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            new_click = (last_clicked["lat"], last_clicked["lng"])
            if st.session_state["admin_last_clicked"] != new_click:
                st.session_state["admin_last_clicked"] = new_click
                with st.spinner("Đang định danh đoạn đường..."):
                    edge_data, err = api_nearest_edge(new_click[0], new_click[1])
                    st.session_state["selected_edge"] = edge_data if not err else None
                st.rerun()

    with c2:
        st.markdown("#### Thao tác chặn đường")

        if st.session_state["admin_last_clicked"]:
            lat, lon = st.session_state["admin_last_clicked"]
            st.success(f"Tọa độ chọn: `{lat:.6f}, {lon:.6f}`")

            if st.session_state["selected_edge"]:
                edge = st.session_state["selected_edge"]
                is_bl = edge["is_blocked"]

                st.markdown(f"""
                <div style='background: #F1F5F9; padding: 10px; border-radius: 6px; margin: 8px 0;'>
                    <div>🏷️ <b>Loại đường:</b> <code>{edge['highway'].upper()}</code></div>
                    <div>📏 <b>Chiều dài:</b> <code>{edge['length_m']}m</code></div>
                    <div>🔗 <b>Giao lộ:</b> <code>{edge['u']}</code> ➔ <code>{edge['v']}</code></div>
                    <div style='margin-top: 6px;'>🚦 <b>Trạng thái:</b> {'<span style="color:#DC2626;font-weight:700">ĐANG BỊ CHẶN 🚧</span>' if is_bl else '<span style="color:#16A34A;font-weight:700">THÔNG SUỐT 🟢</span>'}</div>
                </div>
                """, unsafe_allow_html=True)

                btn_lbl = "🔓 Mở chặn đoạn này" if is_bl else "⛔ Chặn đoạn đường này"
                btn_type = "secondary" if is_bl else "primary"

                if st.button(btn_lbl, type=btn_type, use_container_width=True):
                    if is_bl:
                        _, err = api_unblock_edge(edge["u"], edge["v"])
                        if err:
                            st.error(err)
                        else:
                            st.success("Đã mở chặn tuyến đường!")
                            edge_data, _ = api_nearest_edge(lat, lon)
                            st.session_state["selected_edge"] = edge_data
                            st.rerun()
                    else:
                        _, err = api_block_edge(edge["u"], edge["v"])
                        if err:
                            st.error(err)
                        else:
                            st.success("Đã chặn tuyến đường thành công!")
                            edge_data, _ = api_nearest_edge(lat, lon)
                            st.session_state["selected_edge"] = edge_data
                            st.rerun()
            else:
                st.warning("Không tìm thấy đoạn đường nào quanh vị trí bạn click.")
        else:
            st.info("Nhấp chọn một vị trí trên bản đồ để bắt đầu.")

    st.divider()
    st.markdown("#### Danh sách các tuyến đường đang bị chặn")
    if blocked_list:
        for b_edge in blocked_list:
            col_a, col_b = st.columns([8, 2])
            with col_a:
                st.markdown(f"Đoạn nối Giao lộ `{b_edge['u']}` ➔ `{b_edge['v']}` ({b_edge['name']})")
            with col_b:
                if st.button("Mở chặn", key=f"unb_list_{b_edge['u']}_{b_edge['v']}", use_container_width=True):
                    _, err = api_unblock_edge(b_edge["u"], b_edge["v"])
                    if not err:
                        st.rerun()

        st.divider()
        if st.button("🧹 Khôi phục toàn bộ mạng lưới bản đồ (Mở hết chặn)", type="primary", use_container_width=True):
            _, err = api_clear_blocked()
            if not err:
                st.success("Đã mở chặn toàn bộ mạng lưới giao thông!")
                st.rerun()
    else:
        st.info("Hiện không có sự cố giao thông nào được thiết lập. Toàn bộ mạng lưới đường phố đang thông suốt.")


def _data_tab():
    st.subheader("📊 Quản lý Dữ liệu & Đồ thị Không gian")
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown("#### Trạng thái Đồ thị")
        info, err = api_graph_info()
        if err:
            st.error(f"Lỗi truy vấn: {err}")
        else:
            if info.get("loaded"):
                st.success("Đồ thị đã tải trong RAM và sẵn sàng phục vụ")
                st.markdown(f"""
                - **Số nút giao (Nodes):** `{info['node_count']:,}`
                - **Số đoạn đường (Edges):** `{info['edge_count']:,}`
                - **Số tuyến đường bị chặn:** `{info['blocked_count']:,}`
                - **Đường dẫn tệp PBF gốc:** `{info['pbf_path']}`
                - **Đường dẫn tệp cache đồ thị:** `{info['graph_path']}`
                """)
            else:
                st.warning("Đồ thị chưa được tải vào bộ nhớ RAM.")

            st.divider()
            st.markdown(f"**Trạng thái Build:** `{info.get('build_status', 'idle').upper()}`")
            if info.get("build_status") == "building":
                st.info("Đồ thị đang được khởi tạo ngầm từ tệp PBF. Thao tác này mất từ 2-6 phút. Vui lòng bấm reload/F5 để cập nhật.")
            elif info.get("build_status") == "error":
                st.error(f"Lỗi build: {info.get('build_error')}")

    with c2:
        st.markdown("#### Tác vụ Quản trị")
        if st.button("⚡ Tái tạo đồ thị từ PBF thô", type="primary", use_container_width=True,
                     help="Parse .pbf, chuyển đổi sang NetworkX và lưu vào data/ (~2-5 phút)"):
            res, err = api_graph_build()
            if err:
                st.error(f"Lỗi: {err}")
            else:
                st.success("Đã kích hoạt tiến trình tạo đồ thị dưới nền. Hãy làm mới sau vài phút.")
                st.rerun()

        if st.button("🔄 Tải lại đồ thị từ tệp cache .pkl", use_container_width=True):
            res, err = api_graph_reload()
            if err:
                st.error(f"Lỗi: {err}")
            else:
                st.success(f"Đã nạp lại thành công! {res['node_count']:,} nodes · {res['edge_count']:,} edges")
                st.rerun()


def page_admin():
    with st.sidebar:
        st.markdown("### 🛠️ Menu Quản Trị")
        menu = st.radio("Chọn chức năng:", ["Tìm đường", "Chặn tuyến đường", "Dữ liệu hệ thống"])
        st.divider()

    if menu == "Tìm đường":
        _map_tab()
    elif menu == "Chặn tuyến đường":
        _blocked_roads_tab()
    else:
        _data_tab()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Boston Smart Route Finder",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

def apply_custom_css():
    st.markdown("""
        <style>
            .main .block-container {
                padding-top: 1rem !important;
                padding-bottom: 1rem !important;
                padding-left: 2rem !important;
                padding-right: 2rem !important;
            }
            div.element-container {
                margin-bottom: 0.4rem !important;
            }
            html, body, [class*="css"], .stMarkdown, p, span, label, select, input, button {
                font-size: 13.5px !important;
            }
            h1, h2, h3, h4, h5, h6 {
                margin-top: 0px !important;
                margin-bottom: 0.3rem !important;
            }
            h1 { font-size: 1.5rem !important; }
            h2 { font-size: 1.25rem !important; }
            h3 { font-size: 1.05rem !important; }
            div[data-testid="stForm"] {
                padding: 0.75rem !important;
                border-radius: 8px !important;
                background-color: #FAFAFA;
            }
            hr {
                margin-top: 0.4rem !important;
                margin-bottom: 0.4rem !important;
            }
            header {
                visibility: hidden !important;
                height: 0px !important;
            }
            footer {
                visibility: hidden !important;
            }
            section[data-testid="stSidebar"] {
                padding-top: 1rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()
init()

# Sidebar: Role Switching
with st.sidebar:
    st.markdown("### 👤 Vai Trò Người Dùng")
    role_choice = st.selectbox(
        "Chọn chế độ trải nghiệm:",
        ["Người dùng thường", "Quản trị viên (Admin)"],
        index=0 if st.session_state["role"] == "user" else 1
    )
    st.session_state["role"] = "admin" if role_choice == "Quản trị viên (Admin)" else "user"
    st.divider()

# Dispatch based on role
if st.session_state["role"] == "admin":
    page_admin()
else:
    page_user()
