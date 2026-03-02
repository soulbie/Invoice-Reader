import streamlit as st
import pandas as pd
import json
from PIL import Image
from google import genai
import time 
import hashlib 
import datetime 
import plotly.express as px 
import re 

# ==========================================
# 1. CẤU HÌNH HỆ THỐNG VÀ KẾT NỐI API
# ==========================================
API_KEY = "..."
client = genai.Client(api_key=API_KEY)

# Chỉ thị hệ thống (System Prompt) cho mô hình ngôn ngữ
PROMPT = """
You are an expert accountant. Extract invoice details from the image and return EXACTLY this JSON format.
IMPORTANT RULES:
1. 'purchase_date' MUST be in YYYY-MM-DD format.
2. 'total_amount' MUST be a pure number, NO text, NO commas (e.g., 59000).
3. 'category' MUST be inferred. Choose ONE from: "Ăn uống", "Mua sắm", "Di chuyển", "Tiện ích", "Giải trí/Thể thao", "Khác".
4. 'description' MUST be a SHORT, recognizable brand name or service type. DO NOT use long legal company names. (e.g., return "Highlands Coffee" instead of "Công Ty TNHH Cao Nguyên", return "Tiền điện" instead of "Tổng công ty Điện lực VN"). Keep it under 5 words if possible.

{
    "description": "Highlands Coffee",
    "purchase_date": "2024-02-25",
    "total_amount": 59000,
    "category": "Ăn uống"
}
DO NOT RETURN ANYTHING ELSE. NO MARKDOWN. ONLY VALID JSON.
"""

# ==========================================
# 2. KHỞI TẠO TRẠNG THÁI PHIÊN LÀM VIỆC (SESSION STATE)
# ==========================================
st.set_page_config(page_title="Hệ thống quản lý chi tiêu", layout="wide")

# Khởi tạo các biến lưu trữ cục bộ nếu chưa tồn tại
if 'expenses' not in st.session_state:
    st.session_state['expenses'] = []
if 'processed_hashes' not in st.session_state:
    st.session_state['processed_hashes'] = []
if 'last_uploaded_csv' not in st.session_state:
    st.session_state['last_uploaded_csv'] = None 

def get_image_hash(file_bytes):
    """Tạo mã băm MD5 để kiểm tra trùng lặp tệp tin."""
    return hashlib.md5(file_bytes).hexdigest()

# Tiền xử lý dữ liệu và cấu trúc hóa Pandas DataFrame
if st.session_state['expenses']:
    df = pd.DataFrame(st.session_state['expenses'])
    
    # Xử lý các trường hợp dữ liệu khuyết thiếu
    if 'category' not in df.columns:
        df['category'] = "Khác"
    df['category'] = df['category'].fillna("Khác")
    
    if 'store_name' in df.columns and 'description' not in df.columns:
        df = df.rename(columns={'store_name': 'description'})
        
    # Chuẩn hóa định dạng thời gian để phân tích
    df['purchase_date'] = pd.to_datetime(df['purchase_date'], errors='coerce')
    df['Year'] = df['purchase_date'].dt.year
    df['Month'] = df['purchase_date'].dt.month
    df['Display_Date'] = df['purchase_date'].dt.strftime('%d/%m/%Y')
else:
    df = pd.DataFrame()

# ==========================================
# 3. GIAO DIỆN BẢNG ĐIỀU KHIỂN (SIDEBAR)
# ==========================================
st.sidebar.title("Bảng điều khiển")

# 3.1 Cấu hình tham số ngân sách
st.sidebar.subheader("Cấu hình ngân sách")
ngan_sach_thang = st.sidebar.number_input("Ngân sách mục tiêu (VNĐ)", min_value=0, value=5000000, step=500000)

st.sidebar.markdown("---")

# 3.2 Bộ lọc truy vấn dữ liệu
st.sidebar.subheader("Bộ lọc dữ liệu")
if not df.empty:
    available_years = sorted(df['Year'].dropna().unique().astype(int).tolist(), reverse=True)
    available_months = sorted(df['Month'].dropna().unique().astype(int).tolist())
    
    selected_year = st.sidebar.selectbox("Lọc theo năm", ["Tất cả"] + available_years)
    selected_month = st.sidebar.selectbox("Lọc theo tháng", ["Tất cả"] + available_months)
    
    filtered_df = df.copy()
    if selected_year != "Tất cả":
        filtered_df = filtered_df[filtered_df['Year'] == selected_year]
    if selected_month != "Tất cả":
        filtered_df = filtered_df[filtered_df['Month'] == selected_month]
else:
    filtered_df = pd.DataFrame()
    selected_year, selected_month = "Tất cả", "Tất cả"
    st.sidebar.info("Vui lòng tải dữ liệu lên để xem thống kê.")

st.sidebar.markdown("---")

# 3.3 Module phục hồi dữ liệu từ bản sao lưu
st.sidebar.subheader("Phục hồi dữ liệu")
restore_file = st.sidebar.file_uploader("Tải lên bản ghi báo cáo (định dạng CSV)", type=["csv"])

if restore_file is not None and st.session_state['last_uploaded_csv'] != restore_file.name:
    try:
        df_restored = pd.read_csv(restore_file)
        
        # Nhận diện động các trường dữ liệu từ các phiên bản báo cáo cũ/mới
        col_date = 'Ngày giao dịch' if 'Ngày giao dịch' in df_restored.columns else ('Ngày' if 'Ngày' in df_restored.columns else None)
        col_desc = 'Nội dung' if 'Nội dung' in df_restored.columns else ('Nhà cung cấp / Đối tác' if 'Nhà cung cấp / Đối tác' in df_restored.columns else ('Cửa hàng' if 'Cửa hàng' in df_restored.columns else None))
        col_amt = 'Giá trị (VNĐ)' if 'Giá trị (VNĐ)' in df_restored.columns else ('Số tiền (VND)' if 'Số tiền (VND)' in df_restored.columns else None)
        
        if col_date and col_desc and col_amt:
            for _, row in df_restored.iterrows():
                parsed_date = pd.to_datetime(row[col_date], dayfirst=True, errors='coerce')
                if pd.isna(parsed_date): 
                    parsed_date = datetime.datetime.now() 
                
                cat = row['Danh mục'] if 'Danh mục' in df_restored.columns else 'Khác'
                
                new_entry = {
                    "description": str(row[col_desc]),
                    "purchase_date": parsed_date.strftime('%Y-%m-%d'),
                    "total_amount": int(str(row[col_amt]).replace(',', '').replace('.', '')), 
                    "category": cat
                }
                st.session_state['expenses'].append(new_entry)
                
            st.session_state['last_uploaded_csv'] = restore_file.name
            st.sidebar.success("Đã phục hồi dữ liệu thành công.")
            time.sleep(1)
            st.rerun() 
        else:
            st.sidebar.error("Lỗi cấu trúc: Tệp CSV thiếu các trường dữ liệu cơ sở.")
    except Exception as e:
        st.sidebar.error(f"Lỗi đọc tệp tin: {e}")

# ==========================================
# 4. KHU VỰC LÀM VIỆC CHÍNH (MAIN WORKSPACE)
# ==========================================
st.title("Hệ thống trích xuất và quản lý chi tiêu")
st.caption("Ứng dụng tự động hóa quy trình ghi nhận và phân tích dữ liệu tài chính cá nhân.")
st.divider() 

col1, col2 = st.columns([1, 1.5])

# Khu vực 1: Module nhập liệu
with col1:
    tab1, tab2 = st.tabs(["Trích xuất bằng AI", "Nhập thủ công"])
    
    # Tính năng xử lý hàng loạt bằng AI OCR
    with tab1:
        uploaded_files = st.file_uploader(
            "Định dạng hỗ trợ: JPG, JPEG, PNG", 
            type=["jpg", "jpeg", "png"], 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            cols = st.columns(3)
            for i, file in enumerate(uploaded_files[:3]):
                cols[i].image(Image.open(file), use_container_width=True)
            
            if st.button("Bắt đầu trích xuất", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                countdown_box = st.empty() 
                
                for i, uploaded_file in enumerate(uploaded_files):
                    file_bytes = uploaded_file.getvalue()
                    file_hash = get_image_hash(file_bytes)
                    
                    if file_hash in st.session_state['processed_hashes']:
                        st.warning(f"Bỏ qua tệp tin đã tồn tại: {uploaded_file.name}")
                        progress_bar.progress((i + 1) / len(uploaded_files))
                        time.sleep(1)
                        continue
                    
                    status_text.info(f"Đang xử lý {i+1}/{len(uploaded_files)}: {uploaded_file.name}...")
                    image = Image.open(uploaded_file)
                    
                    # Thuật toán thử lại (Retry) để xử lý giới hạn tốc độ API (Rate Limiting)
                    wait_times = [20, 60] 
                    thanh_cong = False
                    
                    for attempt in range(len(wait_times) + 1):
                        try:
                            response = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=[PROMPT, image]
                            )
                            raw_text = response.text
                            
                            # Biểu thức chính quy (Regex) làm sạch kết quả đầu ra
                            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                            if json_match:
                                clean_json_string = json_match.group(0)
                            else:
                                clean_json_string = raw_text.replace("```json", "").replace("```", "").strip()
                                
                            extracted_data = json.loads(clean_json_string)
                            
                            if 'category' not in extracted_data:
                                extracted_data['category'] = "Khác"
                                
                            st.session_state['expenses'].append(extracted_data)
                            st.session_state['processed_hashes'].append(file_hash)
                            
                            st.success(f"Hoàn tất: {extracted_data.get('description', 'Không rõ')} ({extracted_data['total_amount']:,} VNĐ)")
                            thanh_cong = True
                            break 
                            
                        except Exception as e:
                            error_msg = str(e)
                            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                                if attempt < len(wait_times):
                                    for sec in range(wait_times[attempt], 0, -1):
                                        countdown_box.warning(f"Đang điều chỉnh lưu lượng API. Kết nối lại sau {sec}s.")
                                        time.sleep(1)
                                    countdown_box.empty()
                                else:
                                    st.error(f"Lỗi: Máy chủ từ chối kết nối đối với tệp {uploaded_file.name}")
                            else:
                                st.error(f"Lỗi phân tích cú pháp tệp {uploaded_file.name}: {error_msg}")
                                if 'raw_text' in locals() and raw_text:
                                    st.info(f"Chuỗi phản hồi không hợp lệ: {raw_text}")
                                break 
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                    if thanh_cong and i < len(uploaded_files) - 1:
                        time.sleep(4) # Thời gian trễ để giảm tải API
                
                status_text.success("Tiến trình xử lý hoàn tất.")
                time.sleep(1.5) 
                st.rerun()

    # Tính năng cập nhật dữ liệu thủ công
    with tab2:
        with st.form("manual_entry_form"):
            st.markdown("**Ghi chép giao dịch thủ công**")
            manual_store = st.text_input("Nội dung / Diễn giải (ví dụ: cước viễn thông, ăn trưa)")
            col_a, col_b = st.columns(2)
            manual_date = col_a.date_input("Ngày giao dịch")
            manual_cat = col_b.selectbox("Danh mục", ["Ăn uống", "Mua sắm", "Di chuyển", "Tiện ích", "Giải trí/Thể thao", "Khác"])
            manual_amount = st.number_input("Số tiền (VNĐ)", min_value=0, step=1000)
            
            if st.form_submit_button("Lưu dữ liệu", type="primary", use_container_width=True):
                if manual_store.strip() == "":
                    st.error("Yêu cầu nhập trường Nội dung chi tiêu.")
                else:
                    new_entry = {
                        "description": manual_store,
                        "purchase_date": manual_date.strftime("%Y-%m-%d"),
                        "total_amount": int(manual_amount),
                        "category": manual_cat
                    }
                    st.session_state['expenses'].append(new_entry)
                    st.success("Bản ghi đã được lưu.")
                    time.sleep(1)
                    st.rerun()

# Khu vực 2: Module báo cáo và hiển thị dữ liệu
with col2:
    if selected_year != "Tất cả" or selected_month != "Tất cả":
        st.subheader(f"Báo cáo thống kê (Tháng {selected_month if selected_month != 'Tất cả' else '...'} / {selected_year if selected_year != 'Tất cả' else '...'})")
    else:
        st.subheader("Báo cáo thống kê tổng quan")
    
    if not filtered_df.empty:
        tong_chi = filtered_df['total_amount'].sum()
        
        # Đánh giá cảnh báo ngân sách
        if ngan_sach_thang > 0:
            ty_le = tong_chi / ngan_sach_thang
            st.write(f"**Tiến độ sử dụng ngân sách:** {tong_chi:,.0f} / {ngan_sach_thang:,.0f} VNĐ")
            st.progress(min(ty_le, 1.0))
            if ty_le > 1.0:
                st.error(f"Cảnh báo: Chi tiêu vượt định mức {(tong_chi - ngan_sach_thang):,.0f} VNĐ.")
            elif ty_le >= 0.8:
                st.warning(f"Lưu ý: Đã sử dụng {ty_le*100:.1f}% hạn mức ngân sách.")
            else:
                st.success(f"Tình trạng ổn định: Số dư khả dụng {ngan_sach_thang - tong_chi:,.0f} VNĐ.")
        else:
            st.metric("Tổng giá trị giao dịch", f"{tong_chi:,.0f} VNĐ")
        
        st.divider()
        chart_col1, chart_col2 = st.columns(2)
        
        # Đồ thị phân tích phân bổ chi tiêu
        with chart_col1:
            st.markdown("**Phân bổ theo nội dung:**")
            fig1 = px.pie(filtered_df, values='total_amount', names='description', hole=0.4)
            fig1.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False) 
            fig1.update_traces(
                textposition='inside', 
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Số tiền: %{value:,.0f} VNĐ<extra></extra>"
            ) 
            st.plotly_chart(fig1, use_container_width=True)
            
        with chart_col2:
            st.markdown("**Phân bổ theo danh mục:**")
            cat_df = filtered_df.groupby("category")["total_amount"].sum().reset_index()
            fig2 = px.pie(cat_df, values='total_amount', names='category', hole=0.4)
            fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
            fig2.update_traces(
                textposition='inside', 
                textinfo='percent+label',
                hovertemplate="<b>Danh mục: %{label}</b><br>Số tiền: %{value:,.0f} VNĐ<extra></extra>"
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        # Bảng dữ liệu chi tiết
        st.markdown("**Bảng truy xuất chi tiết:**")
        display_df = filtered_df[['Display_Date', 'description', 'category', 'total_amount']].rename(
            columns={"Display_Date": "Ngày giao dịch", "description": "Nội dung", "category": "Danh mục", "total_amount": "Giá trị (VNĐ)"}
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        # Trình xuất dữ liệu
        csv_data = display_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("Tải xuống bản ghi (CSV)", data=csv_data, file_name="Bao_Cao.csv", mime="text/csv", type="primary")
    else:
        st.info("Hệ thống chưa ghi nhận dữ liệu giao dịch phù hợp với tham số truy vấn.")