# BOSTON_MAP
Ứng dụng tìm đường trên bản đồ Boston sử dụng dữ liệu OpenStreetMap,
thuật toán Dijkstra & A*, giao diện Streamlit + Folium.

---

## Cấu trúc dự án

```
boston_route_finder/
├── app.py                       
├── modules/
│   ├── __init__.py
│   ├── graph_builder.py         
│   └── routing.py               
├── requirements.txt
├── Dockerfile
└── README.md
## Hướng dẫn chạy nhanh

### 1. Cài thư viện

```bash
pip install -r requirements.txt
```

### 2. Đặt file dữ liệu

Đặt file `boston_massachusetts_osm.pbf` vào **cùng thư mục với `app.py`**,
hoặc cấu hình đường dẫn qua biến môi trường:

```bash
export PBF_PATH=/đường dẫn đến/boston_massachusetts_osm.pbf
```

### 3. Khởi động ứng dụng

```bash
streamlit run app.py
```

Lần đầu chạy: ứng dụng sẽ tự động parse file `.pbf` và build đồ thị. 
Kết quả được lưu vào `boston_graph.pkl` để các lần sau load rất nhanh nhờ `@st.cache_resource`.

---

## Tài khoản demo

| Username | Password | Vai trò |
|----------|----------|---------|
| admin    | admin123 | Admin   |
| user     | user123  | User    |

---

## Tính năng

### Người dùng thường (User)
- Xem bản đồ Boston tương tác
- Chọn điểm xuất phát & điểm đến (từ danh sách preset hoặc nhập tọa độ)
- Chọn thuật toán Dijkstra hoặc A*
- Xem tuyến đường vẽ trên bản đồ + metrics (khoảng cách, thời gian xử lý, số node)

### Quản trị viên (Admin)
- Tất cả tính năng của User
- **Quản lý tài khoản**: xem, sửa role/password/trạng thái, thêm tài khoản mới
- **Quản lý dữ liệu**: build lại đồ thị từ PBF, reload cache, xem thông tin đồ thị
- **So sánh thuật toán**: chạy song song Dijkstra + A* và so sánh hiệu năng

---

## Docker

```bash
# Build image
docker build -t boston-route-finder .

# Run (mount file PBF từ ngoài vào)
docker run -p 8501:8501 \
  -v /đường/dẫn/đến/boston_massachusetts_osm.pbf:/app/boston_massachusetts_osm.pbf \
  boston-route-finder
```

Truy cập: http://localhost:8501

---

## Biến môi trường

| Biến         | Mặc định                       | Mô tả                          |
|--------------|--------------------------------|--------------------------------|
| `PBF_PATH`   | `boston_massachusetts_osm.pbf` | Đường dẫn file PBF đầu vào     |
| `GRAPH_PATH` | `boston_graph.pkl`             | Đường dẫn lưu/load file đồ thị |

---

## Kiến trúc kỹ thuật

```
PBF File
   │
   ▼  pyrosm
graph_builder.py ──► NetworkX MultiDiGraph ──► boston_graph.pkl
                                │                      │
                                │           @st.cache_resource
                                ▼                      │
                         routing.py                    │
                    ┌─────────────────┐                │
                    │  Dijkstra (O(E log V))            │
                    │  A* (O(E log V) + heuristic)      │
                    └────────┬────────┘                │
                             │                         │
                             ▼                         │
                        app.py ◄──────────────────────┘
                   Streamlit + Folium
                    PolyLine on Map
