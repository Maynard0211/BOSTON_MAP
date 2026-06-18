import os

target_file = r"c:\Users\HP\Desktop\learning\project\AI_Introl\BOSTON_MAP\app.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# Định nghĩa code mới của hàm routing_widget (không chứa emoji để an toàn)
new_routing_widget = """def routing_widget(key: str):
    locs  = presets()
    names = list(locs.keys())
    last  = st.session_state.get("last_route", {})

    # 1. Khoi tao session state (Lay tu tuyen duong gan nhat da luu hoac de trong)
    st.session_state.setdefault(f"{key}_start_coords", (last["slat"], last["slon"]) if "slat" in last and last["slat"] else None)
    st.session_state.setdefault(f"{key}_end_coords",   (last["elat"], last["elon"]) if "elat" in last and last["elon"] else None)
    st.session_state.setdefault(f"{key}_click_count",  2 if "slat" in last and last["slat"] and "elat" in last and last["elon"] else 0)
    st.session_state.setdefault(f"{key}_last_processed_click", None)
    st.session_state.setdefault(f"{key}_view_state", "input")  # "input" hoac "result"
    st.session_state.setdefault(f"{key}_results", None)

    # 2. Doc gia tri tu widget input (neu co) de phuc vu dong bo nguoc
    slat = st.session_state.get(f"{key}_slat_form")
    slon = st.session_state.get(f"{key}_slon_form")
    elat = st.session_state.get(f"{key}_elat_form")
    elon = st.session_state.get(f"{key}_elon_form")

    # 3. Dong bo nguoc tu input widget ve coords (de di chuyen Marker khi go so bang tay)
    if slat is not None and slon is not None:
        st.session_state[f"{key}_start_coords"] = (slat, slon)
        if st.session_state[f"{key}_click_count"] == 0:
            st.session_state[f"{key}_click_count"] = 1
    else:
        st.session_state[f"{key}_start_coords"] = None
        if st.session_state[f"{key}_click_count"] > 0:
            st.session_state[f"{key}_click_count"] = 0

    if elat is not None and elon is not None:
        st.session_state[f"{key}_end_coords"] = (elat, elon)
        if st.session_state[f"{key}_click_count"] < 2:
            st.session_state[f"{key}_click_count"] = 2
    else:
        st.session_state[f"{key}_end_coords"] = None
        if st.session_state[f"{key}_click_count"] == 2:
            st.session_state[f"{key}_click_count"] = 1

    # Doc lai toa do chuan sau khi dong bo
    start_coords = st.session_state[f"{key}_start_coords"]
    slat, slon = start_coords if start_coords else (None, None)
    end_coords = st.session_state[f"{key}_end_coords"]
    elat, elon = end_coords if end_coords else (None, None)

    # BO CUC: Chia 2 cot (Trai: Ban do, Phai: Form dieu khien hoac Ket qua)
    col_left, col_right = st.columns([7, 3])

    sn, en = "", ""
    algo = "astar"
    compare = False
    run_btn = False
    reset_btn = False

    with col_right:
        # 1. CHE DO HIEN THI KET QUA TIM DUONG
        if st.session_state[f"{key}_view_state"] == "result" and st.session_state[f"{key}_results"]:
            st.subheader("Ket qua tim duong")
            
            # Nut Quay lai
            if st.button("Quay lai tim kiem", use_container_width=True):
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
                st.rerun()
                
            st.divider()
            
            results = st.session_state[f"{key}_results"]
            for a, d in results:
                st.markdown(f"<span style='color:{ALGO_COLORS[a]};font-weight:700'>{ALGO_NAMES[a]}</span>", unsafe_allow_html=True)
                st.write(f"- Khoang cach: {d['total_distance_m']/1000:.3f} km")
                st.write(f"- Thoi gian: {d['exec_time_ms']:.1f} ms")
                st.write(f"- So nut giao: {d['node_count']:,}")
                st.divider()
        
        # 2. CHE DO NHAP LIEU TIM KIEM
        else:
            default_mode_idx = 0 if last.get("mode") == "Dia diem co san" else 1
            if default_mode_idx == 0 and not names:
                default_mode_idx = 1

            mode = st.radio("Che do nhap diem", ["Dia diem co san", "Toa do thu cong"],
                            index=default_mode_idx, key=f"{key}_mode", horizontal=True)

            # Thong bao huong dan chon diem tren ban do
            if mode == "Toa do thu cong":
                if st.session_state[f"{key}_click_count"] == 0:
                    st.info("Hay click chuot len ban do de chon diem Xuat phat.")
                elif st.session_state[f"{key}_click_count"] == 1:
                    st.info("Da chon diem Xuat phat. Hay click tiep len ban do de chon Diem den.")
                elif st.session_state[f"{key}_click_count"] == 2:
                    st.success("Da chon du 2 diem. Nhap 'Tim duong' hoac click tiep len ban do de chon lai hanh trinh moi.")

            # Form nhap lieu khong dung st.form de dong bo 2 chieu muot ma ngay lap tuc
            if mode == "Dia diem co san" and names:
                default_sn_idx = names.index(last["sn"]) if "sn" in last and last["sn"] in names else 0
                default_en_idx = names.index(last["en"]) if "en" in last and last["en"] in names else (1 if len(names) > 1 else 0)
                
                sn = st.selectbox("Xuat phat", names, index=default_sn_idx, key=f"{key}_sn_form")
                en = st.selectbox("Diem den",  names, index=default_en_idx, key=f"{key}_en_form")
            else:
                # Dong bo toa do hien tai vao session_state cua input widget truoc khi render
                st.session_state[f"{key}_slat_form"] = slat
                st.session_state[f"{key}_slon_form"] = slon
                st.session_state[f"{key}_elat_form"] = elat
                st.session_state[f"{key}_elon_form"] = elon

                st.caption("Xuat phat (Vi do / Kinh do)")
                c_start_lat, c_start_lon = st.columns(2)
                with c_start_lat:
                    st.number_input("Vi do (Lat)", format="%.6f", key=f"{key}_slat_form", label_visibility="collapsed", placeholder="Vi do")
                with c_start_lon:
                    st.number_input("Kinh do (Lon)", format="%.6f", key=f"{key}_slon_form", label_visibility="collapsed", placeholder="Kinh do")
                
                st.caption("Diem den (Vi do / Kinh do)")
                c_end_lat, c_end_lon = st.columns(2)
                with c_end_lat:
                    st.number_input("Vi do (Lat)", format="%.6f", key=f"{key}_elat_form", label_visibility="collapsed", placeholder="Vi do")
                with c_end_lon:
                    st.number_input("Kinh do (Lon)", format="%.6f", key=f"{key}_elon_form", label_visibility="collapsed", placeholder="Kinh do")

            st.divider()
            
            default_algo_idx = 0 if last.get("algo") == "astar" else 1
            algo_label = st.radio("Thuat toan", ["A* (A-Star)", "Dijkstra"],
                                   index=default_algo_idx, key=f"{key}_algo_form", horizontal=True)
            algo    = "astar" if "A*" in algo_label else "dijkstra"
            
            default_compare = last.get("compare", False)
            compare = st.checkbox("So sanh ca hai thuat toan", value=default_compare, key=f"{key}_cmp_form")
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                run_btn = st.button("Tim duong", type="primary", use_container_width=True)
            with c_btn2:
                reset_btn = st.button("Dat lai diem", use_container_width=True)

    # Xu ly nut Reset toa do
    if reset_btn:
        st.session_state[f"{key}_start_coords"] = None
        st.session_state[f"{key}_end_coords"] = None
        st.session_state[f"{key}_click_count"] = 0
        st.session_state[f"{key}_last_processed_click"] = None
        st.session_state[f"{key}_view_state"] = "input"
        st.session_state[f"{key}_results"] = None
        
        # Xoa han gia tri trong session state cua form de reset giao dien ve trong
        st.session_state[f"{key}_slat_form"] = None
        st.session_state[f"{key}_slon_form"] = None
        st.session_state[f"{key}_elat_form"] = None
        st.session_state[f"{key}_elon_form"] = None
        st.rerun()

    # Neu nguoi dung bam Tim duong, lay toa do va goi API
    if run_btn:
        if mode == "Dia diem co san" and names:
            slat, slon = locs[sn]
            elat, elon = locs[en]
            st.session_state[f"{key}_start_coords"] = (slat, slon)
            st.session_state[f"{key}_end_coords"] = (elat, elon)
            st.session_state[f"{key}_slat_form"] = slat
            st.session_state[f"{key}_slon_form"] = slon
            st.session_state[f"{key}_elat_form"] = elat
            st.session_state[f"{key}_elon_form"] = elon
            st.session_state[f"{key}_click_count"] = 2
        else:
            slat = st.session_state[f"{key}_slat_form"]
            slon = st.session_state[f"{key}_slon_form"]
            elat = st.session_state[f"{key}_elat_form"]
            elon = st.session_state[f"{key}_elon_form"]

        if slat is None or slon is None or elat is None or elon is None:
            st.error("Vui long chon day du ca diem di va diem den truoc khi tim duong!")
            st.session_state[f"{key}_view_state"] = "input"
            st.session_state[f"{key}_results"] = None
        else:
            algos = ["astar", "dijkstra"] if compare else [algo]
            results_list = []
            
            with st.spinner("Dang tinh toan..."):
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
                
                # Tu dong luu cau hinh
                save_last_route({
                    "mode": mode,
                    "sn": sn if mode == "Dia diem co san" else "",
                    "en": en if mode == "Dia diem co san" else "",
                    "slat": slat,
                    "slon": slon,
                    "elat": elat,
                    "elon": elon,
                    "algo": algo,
                    "compare": compare
                })
                st.session_state["last_route"] = load_last_route()
                st.rerun()

    # Ban do co so (scrollWheelZoom=False tranh cuon trang lam zoom ban do)
    m = folium.Map(location=[42.3601, -71.0589], zoom_start=13, tiles="CartoDB positron", scrollWheelZoom=False)
    
    if slat and slon:
        folium.Marker([slat, slon], tooltip="Xuat phat", icon=folium.Icon(color="blue", icon="map-marker", prefix="fa")).add_to(m)
    if elat and elon:
        folium.Marker([elat, elon], tooltip="Diem den", icon=folium.Icon(color="red", icon="map-marker", prefix="fa")).add_to(m)

    # Ve cac doan duong dang bi chan bang MAU DO noi bat
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
                tooltip=f"Duong bi chan: {edge['name']}"
            ).add_to(m)

    # Ve duong di tim duoc (neu co trong session state)
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

    # Ve ban do ben cot trai (chieu cao 400px)
    with col_left:
        map_data = st_folium(m, use_container_width=True, height=400, key=f"{key}_map_render", returned_objects=["last_clicked"])
        
        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            click_coord = (last_clicked["lat"], last_clicked["lng"])
            if st.session_state[f"{key}_last_processed_click"] != click_coord:
                st.session_state[f"{key}_last_processed_click"] = click_coord
                
                # Khi click chon diem moi tren ban do, tu dong chuyen ve man hinh nhap lieu va xoa ket qua cu
                st.session_state[f"{key}_view_state"] = "input"
                st.session_state[f"{key}_results"] = None
                
                # Xu ly click chon 2 diem lien tiep hoac chon tu dau
                if st.session_state[f"{key}_click_count"] == 0:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    # Dong bo vao session_state cua input widget
                    st.session_state[f"{key}_slat_form"] = click_coord[0]
                    st.session_state[f"{key}_slon_form"] = click_coord[1]
                    st.rerun()
                elif st.session_state[f"{key}_click_count"] == 1:
                    st.session_state[f"{key}_end_coords"] = click_coord
                    st.session_state[f"{key}_click_count"] = 2
                    # Dong bo vao session_state cua input widget
                    st.session_state[f"{key}_elat_form"] = click_coord[0]
                    st.session_state[f"{key}_elon_form"] = click_coord[1]
                    st.rerun()
                elif st.session_state[f"{key}_click_count"] == 2:
                    st.session_state[f"{key}_start_coords"] = click_coord
                    st.session_state[f"{key}_end_coords"] = None
                    st.session_state[f"{key}_click_count"] = 1
                    # Dong bo vao session_state cua input widget
                    st.session_state[f"{key}_slat_form"] = click_coord[0]
                    st.session_state[f"{key}_slon_form"] = click_coord[1]
                    st.session_state[f"{key}_elat_form"] = None
                    st.session_state[f"{key}_elon_form"] = None
                    st.rerun()]"""

# Tìm và thay thế
start_marker = "def routing_widget(key: str):"
end_marker = "def page_user():"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + new_routing_widget + "\n\n\n" + content[end_idx:]
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("REPLACE_SUCCESS")
else:
    print("REPLACE_ERROR: Markers not found")
