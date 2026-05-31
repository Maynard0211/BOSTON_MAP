"""
app.py — Streamlit Frontend (all-in-one)
=========================================
Chạy:  streamlit run app.py
Biến:  API_URL=http://localhost:8000 (mặc định)
"""

import os
import requests
import json
import streamlit as st
import folium
from streamlit_folium import st_folium

API = os.getenv("API_URL", "http://localhost:8000")
ALGO_COLORS = {"astar": "#2563EB", "dijkstra": "#60A5FA"}
ALGO_NAMES  = {"astar": "A* (A-Star)", "dijkstra": "Dijkstra"}
LAST_ROUTE_FILE = "last_route.json"


# ══════════════════════════════════════════════════════════════════════════════
# FILE CONFIG STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def load_last_route() -> dict:
    """Đọc cấu hình tuyến đường đã chọn gần nhất từ file JSON."""
    if os.path.exists(LAST_ROUTE_FILE):
        try:
            with open(LAST_ROUTE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_last_route(data: dict):
    """Lưu cấu hình tuyến đường đã chọn xuống file JSON."""
    try:
        with open(LAST_ROUTE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# API CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def _call(method: str, path: str, body=None, timeout=30):
    """Gọi API, trả về (data | None, error_msg | None)."""
    try:
        r = getattr(requests, method)(f"{API}{path}", json=body, timeout=timeout)
        return (r.json(), None) if r.ok else (None, r.json().get("detail", r.text))
    except requests.exceptions.ConnectionError:
        return None, f"Khong ket noi duoc server ({API}). Backend dang chay chua?"
    except Exception as e:
        return None, str(e)

# Shortcuts
def api_presets():             return _call("get",    "/api/locations/presets")
def api_route(sl,sn,el,en,a): return _call("post",   "/api/route",             {"start_lat":sl,"start_lon":sn,"end_lat":el,"end_lon":en,"algorithm":a}, timeout=90)
def api_graph_info():          return _call("get",    "/api/graph/info")
def api_graph_build():         return _call("post",   "/api/graph/build",       timeout=600)
def api_graph_reload():        return _call("post",   "/api/graph/reload")
def api_health():              return _call("get",    "/health",                timeout=5)

# API quản lý chặn đường
def api_blocked_edges():       return _call("get",    "/api/graph/blocked")
def api_block_edge(u, v):      return _call("post",   "/api/graph/blocked",     {"u": u, "v": v})
def api_unblock_edge(u, v):    return _call("delete", f"/api/graph/blocked?u={u}&v={v}")
def api_clear_blocked():       return _call("post",   "/api/graph/blocked/clear")
def api_nearest_node(lat, lon):return _call("get",    f"/api/graph/nearest?lat={lat}&lon={lon}")
def api_node_adjacent(node_id):return _call("get",    f"/api/graph/node-adjacent/{node_id}")
def api_nearest_edge(lat, lon):return _call("get",    f"/api/graph/nearest-edge?lat={lat}&lon={lon}")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def init():
    st.session_state.setdefault("role",      "user")  # Mặc định là user thường
    st.session_state.setdefault("presets",   None)
    st.session_state.setdefault("selected_node", None)
    st.session_state.setdefault("adjacent_edges", None)
    
    # Đọc cấu hình tuyến đường đã chọn gần nhất
    st.session_state.setdefault("last_route", load_last_route())

def presets():
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
    last  = st.session_state.get("last_route", {})

    # Khởi tạo session state cho việc click chọn điểm đi/đến (mặc định ban đầu để trống)
    st.session_state.setdefault(f"{key}_start_coords", None)
    st.session_state.setdefault(f"{key}_end_coords", None)
    st.session_state.setdefault(f"{key}_click_count", 0)  # Chưa chọn điểm nào
    st.session_state.setdefault(f"{key}_last_processed_click", None)
    
    # Quản lý trạng thái giao diện (nhập liệu hay xem kết quả)
    st.session_state.setdefault(f"{key}_view_state", "input")  # "input" hoặc "result"
    st.session_state.setdefault(f"{key}_results", None)

    # Đọc tọa độ hiện tại từ session state
    start_coords = st.session_state[f"{key}_start_coords"]
    slat, slon = start_coords if start_coords else (None, None)
    end_coords = st.session_state[f"{key}_end_coords"]
    elat, elon = end_coords if end_coords else (None, None)

    # BỐ CỤC: Chia 2 cột (Trái: Bản đồ, Phải: Form điều khiển hoặc Kết quả)
    col_left, col_right = st.columns([7, 3])

    sn, en = "", ""
    algo = "astar"
    compare = False
    run_btn = False
    reset_btn = False

    with col_right:
        # 1. CHẾ ĐỘ HIỂN THỊ KẾT QUẢ TÌM ĐƯỜNG
        if st.session_state[f"{key}_view_state"] == "result" and st.session_state[f"{key}_results"]:
            st.subheader("Kết quả tìm đường 📍")
            
            # Nút Quay lại
            if st.button("⬅ Quay lại tìm kiếm", use_container_width=True):
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
                st.rerun()
                
            st.divider()
            
            results = st.session_state[f"{key}_results"]
            for a, d in results:
                st.markdown(f"<span style='color:{ALGO_COLORS[a]};font-weight:700'>{ALGO_NAMES[a]}</span>", unsafe_allow_html=True)
                st.write(f"- Khoảng cách: {d['total_distance_m']/1000:.3f} km")
                st.write(f"- Thời gian: {d['exec_time_ms']:.1f} ms")
                st.write(f"- Số nút giao: {d['node_count']:,}")
                st.divider()
        
        # 2. CHẾ ĐỘ NHẬP LIỆU TÌM KIẾM
        else:
            default_mode_idx = 0 if last.get("mode") == "Địa điểm có sẵn" else 1
            if default_mode_idx == 0 and not names:
                default_mode_idx = 1

            mode = st.radio("Chế độ nhập điểm", ["Địa điểm có sẵn", "Tọa độ thủ công"],
                            index=default_mode_idx, key=f"{key}_mode", horizontal=True)

            # Thông báo hướng dẫn chọn điểm trên bản đồ
            if mode == "Tọa độ thủ công":
                if st.session_state[f"{key}_click_count"] == 0:
                    st.info("📍 Hãy click chuột lên bản đồ để chọn điểm **Xuất phát**.")
                elif st.session_state[f"{key}_click_count"] == 1:
                    st.info("📍 Đã chọn điểm Xuất phát. Hãy click tiếp lên bản đồ để chọn **Điểm đến**.")
                elif st.session_state[f"{key}_click_count"] == 2:
                    st.success("🏁 Đã chọn đủ 2 điểm. Nhấp 'Tìm đường' hoặc click tiếp lên bản đồ để chọn lại hành trình mới.")

            with st.form(f"{key}_routing_form"):
                if mode == "Địa điểm có sẵn" and names:
                    default_sn_idx = names.index(last["sn"]) if "sn" in last and last["sn"] in names else 0
                    default_en_idx = names.index(last["en"]) if "en" in last and last["en"] in names else (1 if len(names) > 1 else 0)
                    
                    sn = st.selectbox("Xuất phát", names, index=default_sn_idx, key=f"{key}_sn_form")
                    en = st.selectbox("Điểm đến",  names, index=default_en_idx, key=f"{key}_en_form")
                else:
                    st.caption("Xuất phát (Vĩ độ / Kinh độ)")
                    c_start_lat, c_start_lon = st.columns(2)
                    with c_start_lat:
                        slat_input = st.number_input(f"Vĩ độ xuất phát ({key})", value=slat, format="%.6f", label_visibility="collapsed", placeholder="Vĩ độ")
                    with c_start_lon:
                        slon_input = st.number_input(f"Kinh độ xuất phát ({key})", value=slon, format="%.6f", label_visibility="collapsed", placeholder="Kinh độ")
                    
                    st.caption("Điểm đến (Vĩ độ / Kinh độ)")
                    c_end_lat, c_end_lon = st.columns(2)
                    with c_end_lat:
                        elat_input = st.number_input(f"Vĩ độ đích ({key})", value=elat, format="%.6f", label_visibility="collapsed", placeholder="Vĩ độ")
                    with c_end_lon:
                        elon_input = st.number_input(f"Kinh độ đích ({key})", value=elon, format="%.6f", label_visibility="collapsed", placeholder="Kinh độ")

                st.divider()
                
                default_algo_idx = 0 if last.get("algo") == "astar" else 1
                algo_label = st.radio("Thuật toán", ["A* (A-Star)", "Dijkstra"],
                                       index=default_algo_idx, key=f"{key}_algo_form", horizontal=True)
                algo    = "astar" if "A*" in algo_label else "dijkstra"
                
                default_compare = last.get("compare", False)
                compare = st.checkbox("So sánh cả hai thuật toán", value=default_compare, key=f"{key}_cmp_form")
                
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    run_btn = st.form_submit_button("Tìm đường", type="primary", use_container_width=True)
                with c_btn2:
                    reset_btn = st.form_submit_button("Đặt lại điểm 🔄", use_container_width=True)

    if reset_btn and mode == "Tọa độ thủ công":
        st.session_state[f"{key}_start_coords"] = None
        st.session_state[f"{key}_end_coords"] = None
        st.session_state[f"{key}_click_count"] = 0
        st.session_state[f"{key}_last_processed_click"] = None
        st.session_state[f"{key}_view_state"] = "input"
        st.session_state[f"{key}_results"] = None
        st.rerun()

    # Nếu người dùng bấm Tìm đường, lấy tọa độ và gọi API
    if run_btn:
        if mode == "Địa điểm có sẵn" and names:
            slat, slon = locs[sn]
            elat, elon = locs[en]
            st.session_state[f"{key}_start_coords"] = (slat, slon)
            st.session_state[f"{key}_end_coords"] = (elat, elon)
        else:
            slat = slat_input
            slon = slon_input
            elat = elat_input
            elon = elon_input
            
            if slat is None or slon is None or elat is None or elon is None:
                st.error("Vui lòng chọn đầy đủ cả điểm đi và điểm đến trước khi tìm đường!")
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
            else:
                st.session_state[f"{key}_start_coords"] = (slat, slon)
                st.session_state[f"{key}_end_coords"] = (elat, elon)

        if elat and elon:
            algos = ["astar", "dijkstra"] if compare else [algo]
            results_list = []
            
            with st.spinner("Đang tính toán..."):
                for a in algos:
                    data, err = api_route(slat, slon, elat, elon, a)
                    if err:
                        with col_right:
                            st.error(f"{ALGO_NAMES[a]}: {err}")
                        continue
                    if not data["found"]:
                        with col_right:
                            st.warning(f"{ALGO_NAMES[a]}: {data.get('error','')}")
                        continue
                    results_list.append((a, data))
            
            if results_list:
                st.session_state[f"{key}_results"] = results_list
                st.session_state[f"{key}_view_state"] = "result"
                
                # Tự động lưu cấu hình
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

    # Bản đồ cơ sở (scrollWheelZoom=False tránh cuộn trang làm zoom bản đồ)
    m = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron", scrollWheelZoom=False)
    
    if slat and slon:
        folium.Marker([slat, slon], tooltip="Xuất phát", icon=folium.Icon(color="blue", icon="map-marker", prefix="fa")).add_to(m)
    if elat and elon:
        folium.Marker([elat, elon], tooltip="Điểm đến", icon=folium.Icon(color="red", icon="map-marker", prefix="fa")).add_to(m)

    # Vẽ các đoạn đường đang bị chặn bằng MÀU ĐỎ nổi bật
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
                tooltip=f"Đường bị chặn: {edge['name']}"
            ).add_to(m)

    # Vẽ đường đi tìm được (nếu có trong session state)
    first_coords = None
    results = st.session_state.get(f"{key}_results")
    if results:
        for a, d in results:
            coords = [tuple(c) for c in d["path_coordinates"]]
            folium.PolyLine(coords, weight=5, color=ALGO_COLORS[a], opacity=0.85,
                            tooltip=f"{ALGO_NAMES[a]}: {d['total_distance_m']/1000:.2f} km"
                            ).add_to(m)
            first_coords = first_coords or coords

        if first_coords:
            m.fit_bounds([[min(c[0] for c in first_coords), min(c[1] for c in first_coords)],
                          [max(c[0] for c in first_coords), max(c[1] for c in first_coords)]])

    # Vẽ bản đồ bên cột trái (chiều cao 400px)
    with col_left:
        map_data = st_folium(m, use_container_width=True, height=400, key=f"{key}_map_render", returned_objects=["last_clicked"])
        
        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            click_coord = (last_clicked["lat"], last_clicked["lng"])
            if st.session_state[f"{key}_last_processed_click"] != click_coord:
                st.session_state[f"{key}_last_processed_click"] = click_coord
                
                # Khi click chọn điểm mới trên bản đồ, tự động chuyển về màn hình nhập liệu và xóa kết quả cũ
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
                
                # Xử lý click chọn 2 điểm liên tiếp hoặc chọn từ đầu
                if st.session_state[f"{key}_click_count"] == 0:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    st.rerun()
                elif st.session_state[f"{key}_click_count"] == 1:
                    st.session_state[f"{key}_end_coords"] = click_coord
                    st.session_state[f"{key}_click_count"] = 2
                    st.rerun()
                elif st.session_state[f"{key}_click_count"] == 2:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGES / VIEWS
# ══════════════════════════════════════════════════════════════════════════════

def page_user():
    st.markdown("""
    <div style='text-align:center; padding: 12px 10px; background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); border-radius: 8px; margin-bottom: 12px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
      <h1 style='margin:0; font-size: 1.85rem !important; font-weight: 800; color: white !important;'>🗺️ Boston Route Finder</h1>
      <p style='opacity:0.95; margin: 4px 0 0 0; font-size: 1rem !important; font-weight: 400;'>Hệ thống tìm kiếm đường đi ngắn nhất thông minh dựa trên dữ liệu thực tế</p>
    </div>""", unsafe_allow_html=True)
    routing_widget("user_routing")


# ── Admin Tabs ──────────────────────────────────────────────────────────────

def _map_tab():
    st.title("Tìm đường trên bản đồ")
    routing_widget("admin_routing")


def _blocked_roads_tab():
    st.title("Tạo tình huống chặn tuyến đường (Road Blocking)")
    st.write("Quản trị viên có thể cấm lưu thông trên các đoạn đường để mô phỏng tai nạn/công trình. Thuật toán tìm đường sẽ tự động tránh đi qua các đoạn đường này.")

    # 1. Gọi API lấy danh sách cạnh bị chặn
    blocked_list, _ = api_blocked_edges()

    # 2. Khởi tạo session state cho click chuột và cạnh chọn nếu chưa có
    st.session_state.setdefault("admin_last_clicked", None)
    st.session_state.setdefault("selected_edge", None)

    # 3. Tạo bản đồ cơ sở
    m_admin = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron", scrollWheelZoom=False)
    
    # Vẽ các đoạn đường đang bị chặn trên toàn thành phố (nét đứt màu đỏ)
    if blocked_list:
        for edge in blocked_list:
            coords = [tuple(c) for c in edge["coords"]]
            folium.PolyLine(
                coords, 
                weight=5, 
                color="#DC2626",  # Màu đỏ đậm nổi bật
                opacity=0.9,
                dash_array="5, 8",
                tooltip=f"Đang chặn: {edge['name']}"
            ).add_to(m_admin)

    # Vẽ Marker ghim đỏ tại vị trí vừa click chọn (Google Maps pin style)
    if st.session_state["admin_last_clicked"]:
        clat, clon = st.session_state["admin_last_clicked"]
        folium.Marker(
            [clat, clon],
            tooltip="Điểm bạn chọn",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(m_admin)

    # Vẽ con đường gần nhất đang được chọn (nét vẽ màu vàng cam dày nổi bật)
    if st.session_state["selected_edge"]:
        edge = st.session_state["selected_edge"]
        folium.PolyLine(
            edge["coords"],
            weight=8,
            color="#F59E0B",  # Màu vàng cam nổi bật của Google Maps
            opacity=0.9,
            tooltip=f"Tuyến đường đang chọn: {edge['highway']} (Nối {edge['u']} -> {edge['v']})"
        ).add_to(m_admin)

    # BỐ CỤC: Chia cột trái bản đồ [7 phần], cột phải thao tác [3 phần]
    c1, c2 = st.columns([7, 3])

    with c1:
        st.info("Bấm chuột trực tiếp lên vị trí đường đi trên bản đồ để lấy tọa độ.")
        map_data = st_folium(m_admin, use_container_width=True, height=400, key="admin_blocking_map", returned_objects=["last_clicked"])
        
        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            new_click = (last_clicked["lat"], last_clicked["lng"])
            if st.session_state["admin_last_clicked"] != new_click:
                st.session_state["admin_last_clicked"] = new_click
                # Tự động tìm cạnh gần nhất khi click chuột
                with st.spinner("Đang truy vấn tuyến đường..."):
                    edge_data, err = api_nearest_edge(new_click[0], new_click[1])
                    if not err:
                        st.session_state["selected_edge"] = edge_data
                    else:
                        st.session_state["selected_edge"] = None
                st.rerun()

    with c2:
        st.subheader("Thao tác chặn đường")
        
        if st.session_state["admin_last_clicked"]:
            lat, lon = st.session_state["admin_last_clicked"]
            st.success(f"Điểm được chọn: `{lat:.6f}, {lon:.6f}`")
            
            # Hiển thị thông tin cạnh gần nhất nếu được chọn
            if st.session_state["selected_edge"]:
                edge = st.session_state["selected_edge"]
                
                st.divider()
                st.markdown(f"**Tuyến đường phát hiện:**")
                st.write(f"- Loại đường: `{edge['highway'].upper()}`")
                st.write(f"- Chiều dài: `{edge['length_m']}m`")
                st.write(f"- Nối giữa Giao lộ `{edge['u']}` và `{edge['v']}`")
                
                is_bl = edge["is_blocked"]
                status_txt = "Đang bị chặn 🚧" if is_bl else "Hoạt động thông suốt 🟢"
                st.info(f"Trạng thái: **{status_txt}**")
                
                btn_lbl = "Mở chặn đoạn này" if is_bl else "Chặn đoạn đường này"
                btn_type = "secondary" if is_bl else "primary"
                
                if st.button(btn_lbl, type=btn_type, use_container_width=True):
                    if is_bl:
                        _, err = api_unblock_edge(edge["u"], edge["v"])
                        if err:
                            st.error(err)
                        else:
                            st.success("Đã mở chặn tuyến đường thành công!")
                            # Reload lại dữ liệu cạnh để cập nhật trạng thái
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
                st.warning("Không tìm thấy đoạn đường nào gần vị trí bạn chọn.")
        else:
            st.info("Bấm chọn một điểm trên bản đồ để quản lý.")

    # Danh sách tổng hợp toàn bộ các cạnh bị chặn
    st.divider()
    st.subheader("Các tuyến đường đang bị chặn")
    if blocked_list:
        for b_edge in blocked_list:
            col_a, col_b = st.columns([8, 2])
            with col_a:
                st.markdown(f"Đoạn đường giữa Giao lộ `{b_edge['u']}` và Giao lộ `{b_edge['v']}`")
                st.caption(f"Loại đường: `{b_edge['name']}`")
            with col_b:
                if st.button("Mở chặn", key=f"unb_list_{b_edge['u']}_{b_edge['v']}", use_container_width=True):
                    _, err = api_unblock_edge(b_edge["u"], b_edge["v"])
                    if err: st.error(err)
                    else:
                        st.success("Đã mở chặn!")
                        # Reload
                        if st.session_state.get("admin_last_clicked"):
                            clat, clon = st.session_state["admin_last_clicked"]
                            edge_data, _ = api_nearest_edge(clat, clon)
                            st.session_state["selected_edge"] = edge_data
                        st.rerun()
                        
        st.divider()
        if st.button("Khôi phục TOÀN BỘ mạng lưới bản đồ", type="primary", use_container_width=True):
            _, err = api_clear_blocked()
            if err: st.error(err)
            else:
                st.success("Toàn bộ hệ thống giao thông đã thông suốt!")
                if st.session_state.get("admin_last_clicked"):
                    clat, clon = st.session_state["admin_last_clicked"]
                    edge_data, _ = api_nearest_edge(clat, clon)
                    st.session_state["selected_edge"] = edge_data
                st.rerun()
    else:
        st.info("Hiện không có sự cố giao thông nào được thiết lập. Toàn thành phố hoạt động bình thường.")


def _data_tab():
    st.title("Hệ thống dữ liệu không gian")
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.subheader("Trạng thái Đồ thị")
        info, err = api_graph_info()
        if err: 
            st.error(f"Lỗi: {err}")
        else:
            if info["loaded"]:
                st.success("Đồ thị hoạt động trong RAM")
                st.info(f"- Số nút giao (Nodes): {info['node_count']:,}\n"
                        f"- Số đoạn đường (Edges): {info['edge_count']:,}\n"
                        f"- Cạnh đang bị chặn: {info['blocked_count']:,}\n"
                        f"- Tệp PBF bản đồ gốc: `{info['pbf_path']}`\n"
                        f"- Tệp cache GraphML/PKL: `{info['graph_path']}`")
            else:
                st.warning("Đồ thị chưa được load vào bộ nhớ")
                
            # Trạng thái tiến độ build
            st.divider()
            st.markdown(f"Trạng thái Build: `{info['build_status'].upper()}`")
            if info["build_status"] == "building":
                st.info("Đồ thị đang được tạo lập từ tệp PBF thô ở tiến trình nền. Thao tác này mất từ 3-8 phút. Vui lòng bấm reload/F5 để cập nhật trạng thái.")
                st.spinner("Đang chạy ngầm...")
            elif info["build_status"] == "error":
                st.error(f"Lỗi build gần nhất: {info['build_error']}")
            elif info["build_status"] == "success":
                st.success("Tạo lập đồ thị thành công!")

    with c2:
        st.subheader("Thao tác điều khiển")
        if st.button("Build từ PBF thô", type="primary",
                     help="Parse .pbf, tạo và lưu .pkl, cập nhật RAM ở tiến trình nền (~3-8 phút)"):
            res, err = api_graph_build()
            if err: st.error(f"Lỗi: {err}")
            else:
                st.success("Đã kích hoạt tiến trình tạo lập. Vui lòng làm mới trang sau vài phút.")
                st.rerun()

        if st.button("Reload từ file cache .pkl"):
            res, err = api_graph_reload()
            if err: st.error(f"Lỗi: {err}")
            else: 
                st.success(f"Đã tải lại thành công! {res['node_count']:,} nodes · {res['edge_count']:,} edges")
                st.rerun()


def page_admin():
    with st.sidebar:
        st.markdown("Quản trị viên (Admin)")
        st.divider()
        menu = st.radio("Menu điều khiển", ["Tìm đường", "Chặn tuyến đường", "Dữ liệu hệ thống"])
        st.divider()

    if   menu == "Tìm đường":         _map_tab()
    elif menu == "Chặn tuyến đường":   _blocked_roads_tab()
    else:                                 _data_tab()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Boston Route Finder", page_icon="🗺️",
                   layout="wide", initial_sidebar_state="expanded")

def apply_custom_css():
    st.markdown("""
        <style>
            /* CSS thu gọn giao diện, giảm kích thước và padding */
            .main .block-container {
                padding-top: 1rem !important;
                padding-bottom: 1rem !important;
                padding-left: 2rem !important;
                padding-right: 2rem !important;
            }
            div.element-container {
                margin-bottom: 0.4rem !important;
            }
            /* Giảm cỡ chữ của toàn bộ app */
            html, body, [class*="css"], .stMarkdown, p, span, label, select, input, button {
                font-size: 13px !important;
            }
            /* Tiêu đề gọn gàng */
            h1, h2, h3, h4, h5, h6 {
                margin-top: 0px !important;
                margin-bottom: 0.3rem !important;
            }
            h1 { font-size: 1.5rem !important; }
            h2 { font-size: 1.2rem !important; }
            h3 { font-size: 1rem !important; }
            
            /* Gọn gàng các form và widget */
            div[data-testid="stForm"] {
                padding: 0.6rem !important;
                border-radius: 6px !important;
            }
            hr {
                margin-top: 0.4rem !important;
                margin-bottom: 0.4rem !important;
            }
            /* Ẩn header và footer của Streamlit để tăng diện tích hiển thị */
            header {
                visibility: hidden !important;
                height: 0px !important;
            }
            footer {
                visibility: hidden !important;
            }
            /* Giảm margin cho sidebar */
            section[data-testid="stSidebar"] {
                padding-top: 1rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()
init()

# Sidebar chuyển đổi chế độ User / Admin trực tiếp không cần mật khẩu
with st.sidebar:
    st.markdown("Chế độ vai trò")
    role_choice = st.selectbox("Chọn vai trò:", ["Người dùng thường", "Quản trị viên"],
                               index=0 if st.session_state["role"] == "user" else 1)
    
    st.session_state["role"] = "admin" if role_choice == "Quản trị viên" else "user"
    st.divider()

# Phân trang hiển thị
if st.session_state["role"] == "admin":
    page_admin()
else:
    page_user()
